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
