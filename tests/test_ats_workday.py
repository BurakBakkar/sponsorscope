import json

import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.workday import Workday

HOST = "embl.wd103.myworkdayjobs.com"
SLUG = f"{HOST}/embl"
JOBS = f"https://{HOST}/wday/cxs/embl/embl/jobs"
ROBOTS = f"https://{HOST}/robots.txt"


def posting(i, title):
    return {"title": title, "externalPath": f"/job/Heidelberg/{title.replace(' ', '-')}_R{i}",
            "locationsText": "Heidelberg, Germany", "postedOn": "Posted Yesterday", "bulletFields": [f"R{i}"]}


@pytest.fixture
def allowed(respx_mock):
    respx_mock.get(ROBOTS).mock(return_value=httpx.Response(200, text="User-agent: *\nAllow: /EMBL/\nDisallow: /refreshFacet/\n"))


async def test_pages_through_the_board_and_reads_details_for_new_postings(http, respx_mock, allowed):
    first = [posting(i, f"Job {i}") for i in range(20)]
    jobs = respx_mock.post(JOBS).mock(side_effect=[
        httpx.Response(200, json={"total": 21, "jobPostings": first}),
        httpx.Response(200, json={"total": 0, "jobPostings": [posting(99, "PhD Position Structural Biology")]}),
    ])
    detail = respx_mock.get(url__startswith=f"https://{HOST}/wday/cxs/embl/embl/job/").mock(
        return_value=httpx.Response(200, json={
            "jobPostingInfo": {"jobDescription": "<p>Visa support is provided.</p>", "location": "Heidelberg",
                               "country": {"descriptor": "Germany"}, "startDate": "2026-10-20",
                               "externalUrl": f"https://{HOST}/EMBL/job/Heidelberg/PhD_R99"},
            "hiringOrganization": {"name": "EMBL"}}))
    known = frozenset(f"workday:{SLUG}:R{i}" for i in range(20))
    postings = await Workday().fetch(http, SLUG, known_ids=known)

    assert [json.loads(c.request.content)["offset"] for c in jobs.calls] == [0, 20]
    assert len(postings) == 21 and detail.call_count == 1
    phd = postings[-1]
    assert (phd.id, phd.title, phd.country, phd.posted_at, phd.url) == (
        f"workday:{SLUG}:R99", "PhD Position Structural Biology", "DE", "2026-10-20",
        f"https://{HOST}/EMBL/job/Heidelberg/PhD_R99")
    assert phd.description == "Visa support is provided."
    assert postings[0].description is None and postings[0].location_raw == "Heidelberg, Germany"


async def test_robots_disallowed_site_is_not_crawled(http, respx_mock):
    respx_mock.get("https://asml.wd3.myworkdayjobs.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /ASMLBERLIN/\nDisallow: /ASMLEXT1/\n"))
    jobs = respx_mock.post("https://asml.wd3.myworkdayjobs.com/wday/cxs/asml/asmlext1/jobs")
    with pytest.raises(BoardNotFound, match="robots"):
        await Workday().fetch(http, "asml.wd3.myworkdayjobs.com/asmlext1")
    assert not jobs.called


async def test_unknown_site_and_bad_slug(http, respx_mock, allowed):
    respx_mock.post(JOBS).mock(return_value=httpx.Response(404))
    with pytest.raises(BoardNotFound):
        await Workday().fetch(http, SLUG)
    with pytest.raises(BoardNotFound):
        await Workday().fetch(http, "example.com/embl")


async def test_detail_budget_defers_new_postings_to_a_later_run(http, respx_mock, allowed):
    respx_mock.post(JOBS).mock(return_value=httpx.Response(200, json={
        "total": 3, "jobPostings": [posting(1, "Job 1"), posting(2, "Job 2"), posting(3, "Job 3")]}))
    detail = respx_mock.get(url__startswith=f"https://{HOST}/wday/cxs/embl/embl/job/").mock(
        return_value=httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Hi</p>"}}))
    postings = await Workday(detail_budget=1).fetch(http, SLUG, known_ids=frozenset({f"workday:{SLUG}:R3"}))
    assert [(p.job_id, p.description) for p in postings] == [("R1", "Hi"), ("R2", None), ("R3", None)]
    assert detail.call_count == 1


async def test_probe_respects_robots(http, respx_mock):
    respx_mock.get("https://asml.wd3.myworkdayjobs.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /ASMLEXT1/\n"))
    jobs = respx_mock.post("https://asml.wd3.myworkdayjobs.com/wday/cxs/asml/asmlext1/jobs")
    assert (await Workday().probe(http, "asml.wd3.myworkdayjobs.com/asmlext1")).exists is False
    assert not jobs.called
