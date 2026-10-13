import gzip
import html
import json
from contextlib import contextmanager

import httpx
import pytest
import respx

from sponsorscope import pipeline
from sponsorscope.ats.greenhouse import Greenhouse
from sponsorscope.classify.rules import RulesClassifier
from sponsorscope.matching.names import Overrides
from sponsorscope.registers.gb import CONTENT_API, UkRegister
from sponsorscope.store import db

T = ["2026-10-13T03:00:00+00:00", "2026-10-14T03:00:00+00:00", "2026-10-15T03:00:00+00:00"]
CSV_V1 = "https://assets.publishing.service.gov.uk/media/a1/register-2026-10-12.csv"
CSV_V2 = "https://assets.publishing.service.gov.uk/media/b2/register-2026-10-13.csv"
SPONSORS = ["Acme Widgets Ltd"] + [f"Filler Company {i} Ltd" for i in range(9)]
LONG = " We build reliable widgets for customers across Europe and the wider world, and we care deeply about quality."
CITIES = {"london": "GB", "amsterdam": "NL"}


def uk_csv(names):
    rows = "".join(f'"{n}",London,,Worker (A rating),Skilled Worker\n' for n in names)
    return ("Organisation Name,Town/City,County,Type & Rating,Route\n" + rows).encode()


def gh_job(job_id, title, location, text):
    return {"id": job_id, "internal_job_id": job_id, "title": title,
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}", "location": {"name": location},
            "content": html.escape(f"<p>{text}</p>"), "first_published": "2026-09-30T10:00:00Z"}


JOB_YES = gh_job(1, "Backend Engineer", "London, UK", "We offer visa sponsorship for this role." + LONG)
JOB_NO = gh_job(2, "Data Analyst", "London, UK", "Candidates must have the right to work in the UK." + LONG)
JOB_NL = gh_job(3, "Ingenieur", "Amsterdam, Netherlands",
                "Wij zoeken een ervaren ingenieur die graag samenwerkt met onze klanten in Nederland en daarbuiten. Je werkt in een klein team.")


def ok(jobs):
    return httpx.Response(200, json={"jobs": jobs})


@contextmanager
def sources(csv_url=CSV_V1, csv_bytes=None, boards=None, api_status=200):
    with respx.mock(assert_all_called=False) as m:
        if api_status == 200:
            m.get(CONTENT_API).mock(return_value=httpx.Response(200, json={"details": {"attachments": [{"url": csv_url}]}}))
        else:
            m.get(CONTENT_API).mock(return_value=httpx.Response(api_status))
        csv_route = m.get(csv_url).mock(return_value=httpx.Response(200, content=csv_bytes or uk_csv(SPONSORS)))
        for slug, response in (boards or {"acme": ok([JOB_YES, JOB_NO, JOB_NL])}).items():
            m.get(host="boards-api.greenhouse.io", path=f"/v1/boards/{slug}/jobs").mock(return_value=response)
        yield csv_route


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def seeds(tmp_path):
    path = tmp_path / "seeds.yaml"
    path.write_text("- {ats: greenhouse, slug: acme, name: Acme Widgets}\n")
    return path


async def run(conn, http, tmp_path, seeds, now):
    return await pipeline.nightly(conn, http, registers=[UkRegister()], adapters={"greenhouse": Greenhouse()},
                                  classifier=RulesClassifier(), seeds_path=seeds, overrides=Overrides(),
                                  site_dir=tmp_path / "site", now=now, cities=CITIES)


def shard(tmp_path, cc):
    return json.loads(gzip.decompress((tmp_path / "site" / "data" / f"{cc}.json.gz").read_bytes()))


def active_ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM postings WHERE active = 1")}


async def test_end_to_end_exports_badged_postings(conn, http, tmp_path, seeds):
    with sources():
        report = await run(conn, http, tmp_path, seeds, T[0])
    rows = {r[0]: r for r in shard(tmp_path, "gb")}
    assert set(rows) == {"greenhouse:acme:1", "greenhouse:acme:2"}  # Dutch posting dropped
    yes, no = rows["greenhouse:acme:1"], rows["greenhouse:acme:2"]
    assert yes[8] == "yes" and yes[12] == [["licence", "Licensed sponsor (UK)"]]
    assert no[8] == "no"
    assert report.sources["gb"]["status"] == "ok" and report.sources["gb"]["rows"] == 10
    assert report.ats["greenhouse"]["ok"] == 1
    assert json.loads((tmp_path / "site" / "data" / "last_run.json").read_text())["sources"]["gb"]["status"] == "ok"


async def test_unchanged_version_skips_download(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources() as csv_route:
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert csv_route.call_count == 0 and report.sources["gb"]["status"] == "unchanged"


async def test_failed_register_keeps_rows_and_badges(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources(api_status=500):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert report.sources["gb"]["status"] == "failed"
    assert db.active_sponsor_count(conn, "gb") == 10
    assert {r[0]: r for r in shard(tmp_path, "gb")}["greenhouse:acme:1"][12] != []


async def test_shrink_guard_rejects_truncated_register(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources(csv_url=CSV_V2, csv_bytes=uk_csv(SPONSORS[:1])):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert report.sources["gb"]["status"] == "failed" and "shrink" in report.sources["gb"]["error"]
    assert db.active_sponsor_count(conn, "gb") == 10 and db.get_source_version(conn, "gb") == CSV_V1


async def test_failed_board_does_not_deactivate(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    before = active_ids(conn)
    with sources(boards={"acme": httpx.Response(500)}):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert active_ids(conn) == before and report.ats["greenhouse"]["failed"] == 1


async def test_missing_posting_is_deactivated(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources(boards={"acme": ok([JOB_YES, JOB_NL])}):
        await run(conn, http, tmp_path, seeds, T[1])
    assert "greenhouse:acme:2" not in active_ids(conn)


async def test_ats_outage_blocks_deactivation(conn, http, tmp_path):
    seeds = tmp_path / "seeds.yaml"
    seeds.write_text("".join(f"- {{ats: greenhouse, slug: {s}, name: {n}}}\n" for s, n in
                             [("acme", "Acme Widgets"), ("b1", "Beta One"), ("b2", "Beta Two"), ("b3", "Beta Three")]))
    healthy = {"acme": ok([JOB_YES, JOB_NO]), "b1": ok([]), "b2": ok([]), "b3": ok([])}
    with sources(boards=healthy):
        await run(conn, http, tmp_path, seeds, T[0])
    broken = {"acme": ok([JOB_YES]), "b1": httpx.Response(500), "b2": httpx.Response(500), "b3": httpx.Response(500)}
    with sources(boards=broken):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert report.ats["greenhouse"]["outage"] is True
    assert "greenhouse:acme:2" in active_ids(conn)


async def test_board_gone_after_three_404s(conn, http, tmp_path, seeds):
    for now in T:
        with sources(boards={"acme": httpx.Response(404)}):
            await run(conn, http, tmp_path, seeds, now)
    assert db.boards_to_crawl(conn) == []


async def test_rerun_does_not_relabel(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    labels_before = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    with sources():
        await run(conn, http, tmp_path, seeds, T[1])
    assert conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == labels_before == 2


def test_run_match_respects_overrides(conn):
    from sponsorscope.models import SponsorRecord

    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", n) for n in
                                    ("Apple Ltd", "Stripe Payments UK Ltd")], "v1", T[0])
    apple = db.get_or_create_company(conn, "Apple")
    stripe = db.get_or_create_company(conn, "Stripe")
    assert pipeline.run_match(conn, Overrides()) == 1  # apple ↔ "apple" exact; stripe unmatched
    o = Overrides(force={("stripe", "stripe payments")}, forbid={("apple", "apple")})
    assert pipeline.run_match(conn, o) == 1
    pairs = {(r["company_id"], r["method"]) for r in conn.execute("SELECT * FROM sponsor_matches")}
    assert pairs == {(stripe, "manual")} and apple not in {c for c, _ in pairs}
