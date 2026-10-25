import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.pinpoint import Pinpoint

URL = "https://iwbi.pinpointhq.com/jobs.json"
JOB = {"id": "603321", "title": "Content Marketing Manager ",
       "description": "<div><!--block-->We are actively recruiting for this position.<br><br></div>",
       "key_responsibilities": "<ul><li><!--block-->Lead the content calendar</li></ul>",
       "skills_knowledge_expertise": "<ul><li><!--block-->At least 4 years of experience&nbsp;</li></ul>",
       "benefits": "<ul><li><!--block-->Medical, Dental &amp; Vision Coverage</li></ul>",
       "benefits_header": "Benefits", "deadline_at": None, "employment_type": "full_time",
       "workplace_type": "hybrid", "workplace_type_text": "Hybrid",
       "url": "https://iwbi.pinpointhq.com/en/jobs/603321", "path": "/en/jobs/603321",
       "department": {"id": "1", "name": "Marketing"}, "location": {"id": "51630", "name": "New York, NY"}}
GERMANY = {**JOB, "id": "402684", "url": None, "path": "/en/jobs/402684", "workplace_type": None,
           "description": "<p>Fully remote role.</p>", "location": {"id": "54655", "name": "Germany"}}


async def test_parses_jobs(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"data": [JOB, GERMANY]}))
    p, q = await Pinpoint().fetch(http, "iwbi")
    assert (p.id, p.title, p.url, p.location_raw, p.country, p.remote, p.posted_at) == (
        "pinpoint:iwbi:603321", "Content Marketing Manager", "https://iwbi.pinpointhq.com/en/jobs/603321",
        "New York, NY", None, "hybrid", None)
    assert p.description == ("We are actively recruiting for this position.\nLead the content calendar\n"
                             "At least 4 years of experience\nMedical, Dental & Vision Coverage")
    assert (q.url, q.country, q.remote) == ("https://iwbi.pinpointhq.com/en/jobs/402684", "DE", None)


async def test_missing_and_unsafe_slugs(http, respx_mock):
    respx_mock.get("https://nope.pinpointhq.com/jobs.json").mock(
        return_value=httpx.Response(404, text="<!DOCTYPE html>", headers={"content-type": "text/html"}))
    respx_mock.get("https://moved.pinpointhq.com/jobs.json").mock(
        return_value=httpx.Response(200, text="<!DOCTYPE html>", headers={"content-type": "text/html"}))
    for slug in ("nope", "moved"):
        with pytest.raises(BoardNotFound):
            await Pinpoint().fetch(http, slug)
        assert (await Pinpoint().probe(http, slug)).exists is False
    assert (await Pinpoint().probe(http, "evil.example.com/x")).exists is False  # never builds a hostile host
    with pytest.raises(BoardNotFound):
        await Pinpoint().fetch(http, "Bad_Slug")


async def test_other_errors_raise(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        await Pinpoint().fetch(http, "iwbi")


async def test_probe_existing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await Pinpoint().probe(http, "iwbi")).exists is True
