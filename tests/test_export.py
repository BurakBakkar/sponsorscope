import gzip
import json

import pytest

from sponsorscope.export.shards import FIELDS, badge_text, export_site
from sponsorscope.models import Label, RawPosting, SponsorRecord
from sponsorscope.store import db

T1 = "2026-10-13T03:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def add_posting(conn, company_id, job_id, country, lang="en", label=Label("yes", False, (), ("We offer visa sponsorship",))):
    p = RawPosting(ats="greenhouse", slug="acme", job_id=job_id, title=f"Job {job_id}", url=f"https://x/{job_id}",
                   description="d", location_raw="London", country=None, remote=None, posted_at="2026-10-01")
    db.upsert_posting(conn, p, company_id=company_id, country=country, lang=lang, content_hash=f"h{job_id}", now=T1)
    if label:
        db.save_label(conn, p.id, f"h{job_id}", "rules-1", label)


def read_shard(site, cc):
    return json.loads(gzip.decompress((site / "data" / f"{cc}.json.gz").read_bytes()))


def test_empty_db_exports_valid_empty_index(conn, tmp_path):
    counts = export_site(conn, tmp_path / "site", "rules-1", T1)
    index = json.loads((tmp_path / "site" / "data" / "index.json").read_text())
    assert counts == {}
    assert index["countries"] == {} and index["fields"] == FIELDS and index["companies"] == []


def test_shards_badges_and_filters(conn, tmp_path):
    acme = db.get_or_create_company(conn, "Acme Widgets")
    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", "Acme Widgets Ltd")], "v1", T1)
    sponsor_id = conn.execute("SELECT id FROM sponsors").fetchone()[0]
    db.replace_matches(conn, [(sponsor_id, acme, "exact", 100.0)])
    add_posting(conn, acme, "1", "GB")
    add_posting(conn, acme, "2", "NL")  # matched company, but no NL sponsor → no badge
    add_posting(conn, acme, "3", None)  # unknown location → xx shard, no badge
    add_posting(conn, acme, "4", "GB", lang="other")  # non-English → excluded
    add_posting(conn, acme, "5", "GB", label=None)  # no label yet → exported as unknown
    conn.execute("UPDATE postings SET active = 0 WHERE id = 'greenhouse:acme:2'")
    add_posting(conn, acme, "6", "NL")

    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "zz.json.gz").write_bytes(b"stale")
    counts = export_site(conn, site, "rules-1", T1, run_report={"sources": {"gb": {"status": "ok"}}})

    assert counts == {"GB": 2, "NL": 1, "XX": 1}
    assert not (site / "data" / "zz.json.gz").exists()
    gb = {r[0]: dict(zip(FIELDS, r)) for r in read_shard(site, "gb")}
    assert gb["greenhouse:acme:1"]["badges"] == [["licence", "Licensed sponsor (UK)"]]
    assert gb["greenhouse:acme:1"]["sponsorship"] == "yes"
    assert gb["greenhouse:acme:1"]["evidence"] == ["We offer visa sponsorship"]
    assert gb["greenhouse:acme:5"]["sponsorship"] == "unknown"
    nl = [dict(zip(FIELDS, r)) for r in read_shard(site, "nl")]
    assert nl[0]["badges"] == []
    xx = [dict(zip(FIELDS, r)) for r in read_shard(site, "xx")]
    assert xx[0]["country"] is None and xx[0]["badges"] == []

    index = json.loads((site / "data" / "index.json").read_text())
    assert index["companies"] == ["Acme Widgets"] and index["ats"] == ["greenhouse"]
    assert index["sources"]["gb"]["status"] == "ok" and index["sources"]["gb"]["data_as_of"] == T1
    assert json.loads((site / "data" / "last_run.json").read_text())["sources"]["gb"]["status"] == "ok"


def test_retired_sponsor_gives_no_badge(conn, tmp_path):
    acme = db.get_or_create_company(conn, "Acme Widgets")
    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", "Acme Widgets Ltd")], "v1", T1)
    sponsor_id = conn.execute("SELECT id FROM sponsors").fetchone()[0]
    db.replace_matches(conn, [(sponsor_id, acme, "exact", 100.0)])
    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", "Other Co Ltd")], "v2", "2026-10-14T03:00:00+00:00")
    add_posting(conn, acme, "1", "GB")
    export_site(conn, tmp_path / "site", "rules-1", T1)
    assert dict(zip(FIELDS, read_shard(tmp_path / "site", "gb")[0]))["badges"] == []


def test_badge_text():
    assert badge_text("gb", "licence", "GB", None, None) == "Licensed sponsor (UK)"
    assert badge_text("us", "history", "US", 37, "FY2026") == "Filed 37 certified H-1B LCAs (FY2026)"
    assert badge_text("ca", "history", "CA", 12, "2026 Q1") == "12 positive LMIAs (2026 Q1)"
    assert badge_text("ie", "history", "IE", 8, "2026") == "8 employment permits issued (2026)"
