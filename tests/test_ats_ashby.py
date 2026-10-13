import httpx
import pytest

from sponsorscope.ats.ashby import Ashby
from sponsorscope.ats.base import BoardNotFound

URL = "https://api.ashbyhq.com/posting-api/job-board/notion"
JOB = {
    "id": "0d1c-uuid", "title": "Software Engineer, Infrastructure ", "jobUrl": "https://jobs.ashbyhq.com/notion/0d1c-uuid",
    "descriptionPlain": "We can sponsor visas.\nBuild infra.", "descriptionHtml": "<p>ignored</p>",
    "location": "San Francisco, California", "isRemote": True, "workplaceType": "Hybrid", "isListed": True,
    "address": {"postalAddress": {"addressCountry": "United States", "addressLocality": "San Francisco"}},
    "publishedAt": "2024-03-04T14:29:08.532+00:00",
}


async def test_parses_and_prefers_workplace_type_over_is_remote(http, respx_mock):
    unlisted = {**JOB, "id": "hidden", "isListed": False}
    eu = {**JOB, "id": "eu", "workplaceType": None, "isRemote": None, "location": "Remote - European Union",
          "descriptionPlain": None, "descriptionHtml": "<p>Hello <b>EU</b></p>",
          "address": {"postalAddress": {"addressCountry": "European Union"}}}
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"jobs": [JOB, unlisted, eu], "apiVersion": "1"}))
    postings = await Ashby().fetch(http, "notion")
    assert [p.id for p in postings] == ["ashby:notion:0d1c-uuid", "ashby:notion:eu"]
    p = postings[0]
    assert (p.title, p.url, p.country, p.remote, p.posted_at) == (
        "Software Engineer, Infrastructure", "https://jobs.ashbyhq.com/notion/0d1c-uuid", "US", "hybrid", "2024-03-04")
    assert p.description.startswith("We can sponsor visas.")
    assert postings[1].country is None and postings[1].remote == "remote" and postings[1].description == "Hello EU"


async def test_missing_board(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(BoardNotFound):
        await Ashby().fetch(http, "notion")
    assert (await Ashby().probe(http, "notion")).exists is False


async def test_probe_existing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"jobs": []}))
    assert (await Ashby().probe(http, "notion")).exists is True
