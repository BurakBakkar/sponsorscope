import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.rippling import Rippling

API = "https://api.rippling.com/platform/api/ats/v1/board/consulting-careers/jobs"
BOARD = "https://ats.rippling.com/consulting-careers/jobs"
A, B, C = "bd8ed09a-6cf3-4610-8afc-4b8a5e86eff7", "7485103e-4569-4f37-b26c-e89d7fd02d55", "d544cc80-ec25-4eb2-b415-e0cbc429a70b"


def item(uuid, name, location):
    return {"uuid": uuid, "name": name, "department": {"id": "Consulting", "label": "Consulting"},
            "url": f"https://ats.rippling.com/consulting-careers/jobs/{uuid}",
            "workLocation": {"label": location, "id": location}}


LISTING = [item(A, "Senior Consultant", "Remote (United States)"), item(A, "Senior Consultant", "New York, NY"),
           item(B, "Business Analyst", "New York, NY"), item(C, "Data Engineer", "Warszawa, Poland")]


def detail(uuid, locations, created="2024-12-17T08:31:50.337000-08:00"):
    return {"uuid": uuid, "name": "Senior Consultant", "workLocations": locations, "createdOn": created,
            "companyName": "Eclipse Consulting Group",
            "description": {"company": "<div><body><p style='font-size:11pt'><b>About Eclipse</b></p></body></div>",
                            "role": '<meta><h4 dir="ltr"><span>Additional details </span></h4>'
                                    "<p>We are unable to sponsor&nbsp;visas.</p><ul><li>SQL</li></ul>"},
            "employmentType": {"label": "SALARIED_FT", "id": "Salaried, full-time"}}


async def test_parses_list_and_detail_and_skips_known_ids(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json=LISTING))
    a = respx_mock.get(f"{API}/{A}").mock(return_value=httpx.Response(200, json=detail(A, ["New York, NY", "Remote (United States)"])))
    b = respx_mock.get(f"{API}/{B}").mock(return_value=httpx.Response(200, json=detail(B, ["New York, NY"])))
    c = respx_mock.get(f"{API}/{C}").mock(return_value=httpx.Response(404, json={"ok": False}))
    postings = await Rippling().fetch(http, "consulting-careers", known_ids=frozenset({f"rippling:consulting-careers:{B}"}))
    assert [p.job_id for p in postings] == [A, B, C]  # A's second location row is folded in
    assert (a.call_count, b.call_count, c.call_count) == (1, 0, 1)
    first, known, missing = postings
    assert first.description == "About Eclipse\nAdditional details\nWe are unable to sponsor visas.\nSQL"
    assert (first.title, first.url, first.location_raw, first.country, first.remote, first.posted_at) == (
        "Senior Consultant", f"{BOARD}/{A}", "New York, NY; Remote (United States)", None, "remote", "2024-12-17")  # NY: no country evidence
    assert (known.description, known.location_raw, known.country, known.remote) == (None, "New York, NY", None, None)
    assert (missing.description, missing.location_raw, missing.country, missing.posted_at) == (
        "", "Warszawa, Poland", "PL", None)


async def test_missing_board_is_board_not_found(http, respx_mock):
    body = {"error_code": "RESOURCE_NOT_FOUND", "message": "Job Board not found", "resource": None}
    respx_mock.get(API).mock(return_value=httpx.Response(404, json=body))
    respx_mock.get(BOARD).mock(return_value=httpx.Response(404, text="<html>Not Found</html>"))
    with pytest.raises(BoardNotFound):
        await Rippling().fetch(http, "consulting-careers")
    assert (await Rippling().probe(http, "consulting-careers")).exists is False


@pytest.mark.parametrize("slug", ["../board/x", "Consulting-Careers", "a/b", "-x", "x?y=1", ""])
async def test_unsafe_slug_never_hits_the_network(http, respx_mock, slug):
    with pytest.raises(BoardNotFound):
        await Rippling().fetch(http, slug)
    assert (await Rippling().probe(http, slug)).exists is False
    assert not respx_mock.calls


async def test_probe_reads_company_name_from_board_page(http, respx_mock):
    page = ('<html><head><title>Career Opportunities</title></head><body>'
            '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"apiData":{"jobBoard":'
            '{"slug":"somos-inc","title":"Career Opportunities","companyName":"Somos, Inc.","isTest":false},'
            '"jobBoardSlug":"somos-inc"}}}}</script></body></html>')
    respx_mock.get("https://ats.rippling.com/somos-inc/jobs").mock(return_value=httpx.Response(200, text=page))
    respx_mock.get("https://api.rippling.com/platform/api/ats/v1/board/somos-inc/jobs").mock(
        return_value=httpx.Response(200, json=[]))
    result = await Rippling().probe(http, "somos-inc")
    assert (result.exists, result.name) == (True, "Somos, Inc.")
    assert await Rippling().fetch(http, "somos-inc") == []


async def test_detail_budget_defers_new_postings(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json=LISTING))
    respx_mock.get(f"{API}/{A}").mock(return_value=httpx.Response(200, json=detail(A, ["New York, NY"])))
    postings = await Rippling(detail_budget=1).fetch(http, "consulting-careers", known_ids=frozenset({f"rippling:consulting-careers:{C}"}))
    assert [(p.job_id, p.description is None) for p in postings] == [(A, False), (B, True), (C, True)]
