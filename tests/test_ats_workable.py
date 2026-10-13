import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.workable import Workable

URL = "https://apply.workable.com/api/v1/widget/accounts/huggingface"
JOB = {
    "title": "ML Engineer", "shortcode": "81B46579FE", "code": "", "url": "https://apply.workable.com/j/81B46579FE",
    "shortlink": "https://apply.workable.com/j/81B46579FE", "country": "France", "city": "Paris", "state": "Île-de-France",
    "telecommuting": True, "published_on": "2026-10-01", "created_at": "2026-09-30",
    "description": "<p>We offer <b>visa sponsorship</b>.</p>",
    "locations": [{"country": "France", "countryCode": "FR", "city": "Paris", "region": "Île-de-France", "hidden": False}],
}


async def test_parses_jobs_with_details(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"name": "Hugging Face", "jobs": [JOB]}))
    [p] = await Workable().fetch(http, "huggingface")
    assert route.calls.last.request.url.params["details"] == "true"
    assert (p.id, p.title, p.country, p.remote, p.posted_at) == (
        "workable:huggingface:81B46579FE", "ML Engineer", "FR", "remote", "2026-10-01")
    assert p.location_raw == "Paris, Île-de-France, France"
    assert p.description == "We offer visa sponsorship."


async def test_country_falls_back_to_country_name(http, respx_mock):
    job = {**JOB, "locations": [], "telecommuting": False, "country": "Netherlands"}
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"name": "HF", "jobs": [job]}))
    [p] = await Workable().fetch(http, "huggingface")
    assert p.country == "NL" and p.remote is None


async def test_probe_and_missing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"name": "Hugging Face", "jobs": []}))
    result = await Workable().probe(http, "huggingface")
    assert result.exists and result.name == "Hugging Face" and Workable.provides_name
    respx_mock.get("https://apply.workable.com/api/v1/widget/accounts/nope").mock(return_value=httpx.Response(404))
    assert (await Workable().probe(http, "nope")).exists is False
    with pytest.raises(BoardNotFound):
        await Workable().fetch(http, "nope")
