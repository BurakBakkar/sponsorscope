import pytest

from sponsorscope.ats.base import ProbeResult
from sponsorscope.discovery.probe import run_discovery
from sponsorscope.discovery.seeds import Seed
from sponsorscope.discovery.slugs import candidates
from sponsorscope.models import SponsorRecord
from sponsorscope.store import db

T1, T2 = "2026-10-13T03:00:00+00:00", "2026-10-21T03:00:00+00:00"


class FakeATS:
    def __init__(self, name, provides_name, boards, errors=()):
        self.name, self.provides_name, self.boards, self.errors = name, provides_name, boards, set(errors)
        self.probed = []

    async def probe(self, http, slug):
        self.probed.append(slug)
        if slug in self.errors:
            raise RuntimeError("HTTP 502")
        return ProbeResult(slug in self.boards, self.boards.get(slug))


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def sponsors(conn, *names, source="gb"):
    db.upsert_sponsors(conn, source, [SponsorRecord("GB", source, "licence", n) for n in names], "v1", T1)


def boards(conn):
    return {(r["ats"], r["slug"]): (r["status"], r["origin"]) for r in conn.execute("SELECT * FROM boards")}


def test_candidates():
    assert candidates("monzo bank", verifiable=True) == ["monzobank", "monzo-bank", "monzo"]
    assert candidates("monzo bank", verifiable=False) == ["monzobank", "monzo-bank"]
    assert candidates("acme data", verifiable=False) == ["acmedata", "acme-data"]  # compact length 8 → allowed
    assert candidates("acme dat", verifiable=False) == []  # compact length 7 → too collision-prone without a name check
    assert candidates("northwind trading", verifiable=False) == ["northwindtrading", "northwind-trading"]
    assert candidates("ibm", verifiable=True) == []  # short-name guard
    assert candidates("deliveroo", verifiable=True) == ["deliveroo"]
    assert candidates("", verifiable=True) == []


async def test_seeds_are_probed_and_named(conn):
    gh = FakeATS("greenhouse", True, {"airbnb": "Airbnb"})
    lever = FakeATS("lever", False, {"15five": None})
    seeds = [Seed("greenhouse", "airbnb", None), Seed("greenhouse", "deadco", None),
             Seed("lever", "15five", None), Seed("workday", "x", None)]
    summary = await run_discovery(conn, None, {"greenhouse": gh, "lever": lever}, seeds=seeds, now=T1, budget=100)
    assert summary["seeds_added"] == 3 and summary["boards_found"] == 2 and summary["boards_missed"] == 1
    assert boards(conn) == {("greenhouse", "airbnb"): ("hit", "seed"), ("greenhouse", "deadco"): ("miss", "seed"),
                            ("lever", "15five"): ("hit", "seed")}
    names = {r["slug"]: r["display_name"] for r in conn.execute(
        "SELECT b.slug, c.display_name FROM boards b JOIN companies c ON c.id = b.company_id")}
    assert names == {"airbnb": "Airbnb", "15five": "15Five"}


async def test_verified_guess_creates_board_and_wrong_name_is_rejected(conn):
    sponsors(conn, "Monzo Bank Ltd", "Atlas Care Homes Ltd")
    gh = FakeATS("greenhouse", True, {"monzo": "Monzo Bank", "atlas": "Atlas"})
    summary = await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T1, budget=100)
    assert summary["guesses_found"] == 1 and summary["guesses_rejected"] == 1
    assert boards(conn) == {("greenhouse", "monzo"): ("hit", "guess")}
    company = conn.execute("SELECT display_name, norm_name FROM companies").fetchone()
    assert tuple(company) == ("Monzo Bank", "monzo bank")  # will exact-match the sponsor
    progress = {r[0]: r[1] for r in conn.execute("SELECT sponsor_norm, attempts FROM discovery_progress")}
    assert progress == {"monzo bank": 1, "atlas care homes": 1}


async def test_unverifiable_ats_only_gets_long_full_name_guesses(conn):
    sponsors(conn, "Northwind Trading Ltd", "Zeta Ltd")
    lever = FakeATS("lever", False, {"northwindtrading": None, "zeta": None})
    await run_discovery(conn, None, {"lever": lever}, seeds=[], now=T1, budget=100)
    assert "zeta" not in lever.probed and boards(conn) == {("lever", "northwindtrading"): ("hit", "guess")}
    assert conn.execute("SELECT display_name FROM companies").fetchone()[0] == "Northwind Trading"


async def test_budget_caps_probes_and_matched_sponsors_are_skipped(conn):
    sponsors(conn, "Alpha Widgets Ltd", "Bravo Widgets Ltd", "Charlie Widgets Ltd")
    sid = conn.execute("SELECT id FROM sponsors WHERE norm_name = 'alpha widgets'").fetchone()[0]
    db.replace_matches(conn, [(sid, db.get_or_create_company(conn, "Alpha Widgets"), "exact", 100.0)])
    gh = FakeATS("greenhouse", True, {})
    summary = await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T1, budget=3)
    assert summary["probes"] <= 3 and len(gh.probed) == 3
    assert not any(s.startswith("alpha") for s in gh.probed)


async def test_probe_errors_do_not_back_off_or_mark_miss(conn):
    sponsors(conn, "Monzo Bank Ltd")
    gh = FakeATS("greenhouse", True, {}, errors={"monzobank", "monzo-bank", "monzo", "flaky"})
    summary = await run_discovery(conn, None, {"greenhouse": gh}, seeds=[Seed("greenhouse", "flaky", None)], now=T1, budget=100)
    assert summary["probe_errors"] == 4
    assert boards(conn) == {("greenhouse", "flaky"): ("pending", "seed")}
    assert conn.execute("SELECT COUNT(*) FROM discovery_progress").fetchone()[0] == 0


async def test_missed_sponsor_waits_for_backoff(conn):
    sponsors(conn, "Monzo Bank Ltd")
    gh = FakeATS("greenhouse", True, {})
    await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T1, budget=100)
    gh.probed.clear()
    await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now="2026-10-15T03:00:00+00:00", budget=100)
    assert gh.probed == []
    await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T2, budget=100)
    assert gh.probed == ["monzobank", "monzo-bank", "monzo"]
