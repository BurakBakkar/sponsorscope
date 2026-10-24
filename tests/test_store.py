import pytest

from sponsorscope.models import Label, RawPosting, SponsorRecord
from sponsorscope.store import db

T1, T2 = "2026-10-13T03:00:00+00:00", "2026-10-14T03:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def rec(name, route="Skilled Worker"):
    return SponsorRecord(country="GB", source="gb", evidence="licence", legal_name=name, route=route)


def posting(job_id, title="Engineer"):
    return RawPosting(ats="greenhouse", slug="acme", job_id=job_id, title=title, url="https://x",
                      description="d", location_raw="London", country=None, remote=None, posted_at="2026-10-01")


def test_connect_is_idempotent(tmp_path):
    db.connect(tmp_path / "t.db").close()
    c = db.connect(tmp_path / "t.db")
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sponsors", "source_versions", "companies", "boards", "sponsor_matches", "postings", "labels"} <= tables


def test_upsert_sponsors_and_active_count(conn):
    assert db.upsert_sponsors(conn, "gb", [rec("Acme Ltd"), rec("Beta Ltd")], "v1", T1) == 2
    assert db.get_source_version(conn, "gb") == "v1"
    assert db.active_sponsor_count(conn, "gb") == 2
    db.upsert_sponsors(conn, "gb", [rec("Acme Ltd")], "v2", T2)
    assert db.active_sponsor_count(conn, "gb") == 1  # Beta retired but row kept
    assert conn.execute("SELECT COUNT(*) FROM sponsors").fetchone()[0] == 2


def test_null_route_does_not_duplicate(conn):
    db.upsert_sponsors(conn, "gb", [rec("Acme Ltd", route=None), rec("ACME Limited", route=None)], "v1", T1)
    assert conn.execute("SELECT COUNT(*) FROM sponsors").fetchone()[0] == 1


def test_count_sponsor_keys_matches_upsert_dedupe():
    records = [rec("Acme Ltd"), rec("ACME Limited"), rec("Acme Ltd", route="Global Business Mobility"), rec("Ltd")]
    assert db.count_sponsor_keys(records) == 2  # "Ltd" normalises to "" and is skipped


def test_get_or_create_company_dedupes_by_norm(conn):
    a = db.get_or_create_company(conn, "Acme Ltd")
    assert db.get_or_create_company(conn, "ACME Limited") == a
    assert db.get_or_create_company(conn, "Beta") != a


def test_upsert_board_never_resurrects_gone_board(conn):
    cid = db.get_or_create_company(conn, "Acme")
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T1)
    for _ in range(db.GONE_AFTER):
        db.record_board_result(conn, "greenhouse", "acme", "not_found")
    assert db.boards_to_crawl(conn) == []
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T2)
    assert db.boards_to_crawl(conn) == []


def test_ok_result_resets_not_found_streak(conn):
    cid = db.get_or_create_company(conn, "Acme")
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T1)
    db.record_board_result(conn, "greenhouse", "acme", "not_found")
    db.record_board_result(conn, "greenhouse", "acme", "not_found")
    db.record_board_result(conn, "greenhouse", "acme", "ok")
    db.record_board_result(conn, "greenhouse", "acme", "not_found")
    assert [b["slug"] for b in db.boards_to_crawl(conn)] == ["acme"]


def test_postings_upsert_meta_and_deactivate(conn):
    cid = db.get_or_create_company(conn, "Acme")
    for jid in ("1", "2"):
        db.upsert_posting(conn, posting(jid), company_id=cid, country="GB", lang="en", content_hash=f"h{jid}", now=T1)
    meta = db.get_posting_meta(conn, "greenhouse:acme:1")
    assert meta["content_hash"] == "h1" and meta["lang"] == "en"
    assert db.get_posting_meta(conn, "greenhouse:acme:9") is None
    assert db.deactivate_missing(conn, "greenhouse", "acme", {"greenhouse:acme:1"}) == 1
    active = {r[0] for r in conn.execute("SELECT id FROM postings WHERE active=1")}
    assert active == {"greenhouse:acme:1"}
    db.upsert_posting(conn, posting("2"), company_id=cid, country="GB", lang="en", content_hash="h2", now=T2)
    first_seen = conn.execute("SELECT first_seen, active FROM postings WHERE id='greenhouse:acme:2'").fetchone()
    assert tuple(first_seen) == (T1, 1)  # reactivated, first_seen preserved


def test_labels(conn):
    label = Label("yes", False, ("nl",), ("We offer visa sponsorship",))
    assert not db.has_label(conn, "p1", "h1", "rules-1")
    db.save_label(conn, "p1", "h1", "rules-1", label)
    assert db.has_label(conn, "p1", "h1", "rules-1")
    assert not db.has_label(conn, "p1", "h1", "rules-2")
    row = conn.execute("SELECT * FROM labels").fetchone()
    assert row["languages_required"] == '["nl"]' and row["mixed"] == 0


def test_replace_matches(conn):
    db.replace_matches(conn, [(1, 1, "exact", 100.0), (2, 1, "normalised", 97.0)])
    db.replace_matches(conn, [(3, 2, "manual", 100.0)])
    assert [tuple(r) for r in conn.execute("SELECT sponsor_id, company_id FROM sponsor_matches")] == [(3, 2)]


def test_backoff_schedule():
    assert db.backoff_until(T1, 1) == "2026-10-20T03:00:00+00:00"
    assert db.backoff_until(T1, 2) == "2026-11-10T03:00:00+00:00"
    assert db.backoff_until(T1, 3) == db.backoff_until(T1, 9) == "2027-01-05T03:00:00+00:00"


def test_seed_boards_are_pending_until_probed(conn):
    assert db.add_seed_board(conn, "ashby", "notion", None, T1) is True
    assert db.add_seed_board(conn, "ashby", "notion", None, T1) is False
    assert [r["slug"] for r in db.due_boards(conn, T1, 10)] == ["notion"]
    assert db.boards_to_crawl(conn) == []
    cid = db.get_or_create_company(conn, "Notion")
    db.record_probe(conn, "ashby", "notion", exists=True, company_id=cid, now=T1)
    assert [tuple(r) for r in db.boards_to_crawl(conn)] == [("ashby", "notion", cid)]
    assert db.board_company(conn, "ashby", "notion") == cid and db.due_boards(conn, T2, 10) == []


def test_probe_miss_backs_off(conn):
    db.add_seed_board(conn, "lever", "ghost", None, T1)
    db.record_probe(conn, "lever", "ghost", exists=False, company_id=None, now=T1)
    assert db.due_boards(conn, T2, 10) == []  # next probe in 7 days
    assert len(db.due_boards(conn, "2026-10-21T00:00:00+00:00", 10)) == 1
    db.record_probe(conn, "lever", "ghost", exists=False, company_id=None, now="2026-10-21T00:00:00+00:00")
    row = conn.execute("SELECT status, consecutive_failures, next_probe_at FROM boards").fetchone()
    assert tuple(row) == ("miss", 2, "2026-11-18T00:00:00+00:00")


def test_gone_boards_are_due_for_reprobe(conn):
    cid = db.get_or_create_company(conn, "Acme")
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T1)
    for _ in range(db.GONE_AFTER):
        db.record_board_result(conn, "greenhouse", "acme", "not_found")
    assert [r["status"] for r in db.due_boards(conn, T1, 10)] == ["gone"]


def test_sponsors_to_guess_priority_and_exclusions(conn):
    db.upsert_sponsors(conn, "gb", [rec("Uk Only Widgets Ltd"), rec("Matched Co Ltd")], "v1", T1)
    db.upsert_sponsors(conn, "us", [SponsorRecord("US", "us", "history", "Big Filer Inc", filings=500),
                                    SponsorRecord("US", "us", "history", "Small Filer Inc", filings=3)], "v1", T1)
    matched = conn.execute("SELECT id FROM sponsors WHERE norm_name = 'matched'").fetchone()[0]
    db.replace_matches(conn, [(matched, db.get_or_create_company(conn, "Matched"), "exact", 100.0)])
    assert [r["norm_name"] for r in db.sponsors_to_guess(conn, T1, 10)] == ["big filer", "small filer", "uk only widgets"]
    db.record_guess_attempt(conn, "big filer", found=False, now=T1)
    assert [r["norm_name"] for r in db.sponsors_to_guess(conn, T2, 10)] == ["small filer", "uk only widgets"]
    assert [r["norm_name"] for r in db.sponsors_to_guess(conn, T2, 1)] == ["small filer"]


def test_due_boards_interleave_ats_so_one_host_cannot_eat_the_budget(conn):
    for ats in ("ashby", "greenhouse", "lever"):
        for slug in ("a", "b", "c"):
            db.add_seed_board(conn, ats, slug, None, T1)
    due = [(r["ats"], r["slug"]) for r in db.due_boards(conn, T1, 6)]
    assert sorted({a for a, _ in due}) == ["ashby", "greenhouse", "lever"]
    assert [a for a, _ in due] == ["ashby", "greenhouse", "lever"] * 2


def test_company_name_verification_only_upgrades(conn, tmp_path):
    cid = db.get_or_create_company(conn, "Alpha", verified=False)
    assert conn.execute("SELECT name_verified FROM companies WHERE id = ?", (cid,)).fetchone()[0] == 0
    assert db.get_or_create_company(conn, "Alpha", verified=True) == cid
    db.get_or_create_company(conn, "Alpha", verified=False)
    assert conn.execute("SELECT name_verified FROM companies WHERE id = ?", (cid,)).fetchone()[0] == 1


def test_connect_migrates_old_companies_table(tmp_path):
    import sqlite3
    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, norm_name TEXT NOT NULL UNIQUE)")
    old.execute("INSERT INTO companies (display_name, norm_name) VALUES ('Acme', 'acme')")
    old.commit(); old.close()
    c = db.connect(tmp_path / "old.db")
    assert c.execute("SELECT name_verified FROM companies").fetchone()[0] == 1


def test_connect_adds_level_to_old_postings_and_upsert_stores_it(tmp_path):
    import sqlite3
    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE postings (id TEXT PRIMARY KEY, ats TEXT NOT NULL, slug TEXT NOT NULL, company_id INTEGER,"
                " title TEXT, url TEXT, location_raw TEXT, country TEXT, remote TEXT, posted_at TEXT, content_hash TEXT,"
                " lang TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
    old.commit(); old.close()
    c = db.connect(tmp_path / "old.db")
    cid = db.get_or_create_company(c, "Acme")
    db.upsert_posting(c, posting("1"), company_id=cid, country="GB", lang="en", content_hash="h", now=T1, level="phd")
    db.touch_posting(c, posting("1"), company_id=cid, country="GB", now=T2, level="masters")
    assert c.execute("SELECT level FROM postings").fetchone()[0] == "masters"
