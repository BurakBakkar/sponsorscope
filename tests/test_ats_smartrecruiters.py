import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.smartrecruiters import PAGE_SIZE, SmartRecruiters

API = "https://api.smartrecruiters.com/v1/companies/Acme/postings"


def item(pid, ref, lang="en", country="ro"):
    return {"id": pid, "name": f"Job {pid}", "refNumber": ref, "releasedDate": "2026-10-13T10:52:12.447Z",
            "language": {"code": lang}, "location": {"city": "Bucharest", "country": country, "remote": False,
                                                      "hybrid": True, "fullLocation": "Bucharest, Romania"}}


def detail(text):
    return {"jobAd": {"sections": {"companyDescription": {"title": "About", "text": "<p>Acme&#xa0;Corp</p>"},
                                   "jobDescription": {"title": "Role", "text": f"<p>{text}</p>"},
                                   "qualifications": {"title": "You", "text": ""},
                                   "additionalInformation": {"title": "More", "text": "<p>We can sponsor visas.</p>"}}}}


async def test_paginates_dedupes_languages_and_fetches_details_for_new_ids_only(http, respx_mock):
    page1 = [item(str(i), f"REF{i}") for i in range(PAGE_SIZE)]
    page2 = [item("fr-copy", "REF0", lang="fr"), item("200", "REF200", lang="en-GB")]
    def listing(request):
        offset = int(request.url.params["offset"])
        content = page1 if offset == 0 else page2
        return httpx.Response(200, json={"offset": offset, "limit": PAGE_SIZE, "totalFound": PAGE_SIZE + 2, "content": content})
    respx_mock.get(API).mock(side_effect=listing)
    detail_route = respx_mock.get(url__regex=rf"{API}/\d+$").mock(return_value=httpx.Response(200, json=detail("Build things")))
    known = frozenset(f"smartrecruiters:Acme:{i}" for i in range(1, PAGE_SIZE))  # all but id 0 already stored
    postings = await SmartRecruiters().fetch(http, "Acme", known_ids=known)
    ids = [p.job_id for p in postings]
    assert len(ids) == PAGE_SIZE + 1 and "fr-copy" not in ids and "200" in ids
    assert detail_route.call_count == 2  # ids 0 and 200 are new
    first = next(p for p in postings if p.job_id == "0")
    assert first.description.startswith("Acme Corp") and "We can sponsor visas." in first.description
    assert (first.country, first.remote, first.posted_at, first.url) == (
        "RO", "hybrid", "2026-10-13", "https://jobs.smartrecruiters.com/Acme/0")
    assert next(p for p in postings if p.job_id == "5").description is None


async def test_empty_listing_for_unknown_company_is_board_not_found(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 0, "content": []}))
    respx_mock.get("https://careers.smartrecruiters.com/Acme").mock(return_value=httpx.Response(302, headers={"Location": "https://jobs.smartrecruiters.com/"}))
    with pytest.raises(BoardNotFound):
        await SmartRecruiters().fetch(http, "Acme")


async def test_empty_listing_for_real_company_is_empty_board(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 0, "content": []}))
    respx_mock.get("https://careers.smartrecruiters.com/Acme").mock(return_value=httpx.Response(200, text="<html>"))
    assert await SmartRecruiters().fetch(http, "Acme") == []
    assert (await SmartRecruiters().probe(http, "Acme")).exists is True


async def test_detail_404_gives_empty_description(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 1, "content": [item("7", "R7")]}))
    respx_mock.get(f"{API}/7").mock(return_value=httpx.Response(404, json={"code": "RESOURCE_NOT_FOUND"}))
    [p] = await SmartRecruiters().fetch(http, "Acme")
    assert p.description == ""
