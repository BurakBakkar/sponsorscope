from sponsorscope.report import RunReport


def test_warnings_cover_failed_sources_and_ats_problems():
    r = RunReport(started_at="t0")
    r.source("gb", "ok", rows=10)
    r.source("nl", "failed", error="HTTP 500")
    r.source("fi", "blocked", error="403")
    r.board_summary("greenhouse", boards=10, ok=9, not_found=0, failed=1, postings=50, outage=False, errors=["x: boom"])
    r.board_summary("lever", boards=5, ok=5, not_found=0, failed=0, postings=20, outage=False, errors=[])
    warnings = r.warnings()
    assert any(w.startswith("nl: failed") for w in warnings)
    assert any(w.startswith("fi: blocked") for w in warnings)
    assert any("greenhouse" in w and "1 of 10" in w for w in warnings)
    assert not any(w.startswith("gb") or "lever" in w for w in warnings)


def test_outage_warning():
    r = RunReport(started_at="t0")
    r.board_summary("lever", boards=4, ok=1, not_found=0, failed=3, postings=2, outage=True, errors=[])
    assert any("outage" in w for w in r.warnings())


def test_to_dict_round_trips():
    r = RunReport(started_at="t0")
    r.source("gb", "unchanged", version="v1")
    d = r.to_dict()
    assert d == {"started_at": "t0", "finished_at": None,
                 "sources": {"gb": {"status": "unchanged", "version": "v1"}}, "ats": {}}
