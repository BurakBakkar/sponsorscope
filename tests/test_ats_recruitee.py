import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.recruitee import Recruitee

URL = "https://bunq.recruitee.com/api/offers/"
OFFER = {"id": 2781634, "title": "Senior Product Owner", "status": "published",
         "careers_url": "https://careers.bunq.com/o/senior-product-owner-1",
         "description": "<p>Join bunq.</p>", "requirements": "<ul><li>Fluent English</li></ul>",
         "location": "Amsterdam, Noord-Holland, Netherlands", "country_code": "NL",
         "remote": True, "hybrid": True, "on_site": False, "published_at": "2026-10-13 10:58:56 UTC"}


async def test_parses_offers(http, respx_mock):
    draft = {**OFFER, "id": 1, "status": "draft"}
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"offers": [OFFER, draft]}))
    [p] = await Recruitee().fetch(http, "bunq")
    assert (p.id, p.url, p.country, p.remote, p.posted_at) == (
        "recruitee:bunq:2781634", "https://careers.bunq.com/o/senior-product-owner-1", "NL", "hybrid", "2026-10-13")
    assert p.description == "Join bunq.\nFluent English"


async def test_missing_and_unsafe_slugs(http, respx_mock):
    respx_mock.get("https://nope.recruitee.com/api/offers/").mock(return_value=httpx.Response(404, json={"error": "Not Found"}))
    with pytest.raises(BoardNotFound):
        await Recruitee().fetch(http, "nope")
    assert (await Recruitee().probe(http, "nope")).exists is False
    assert (await Recruitee().probe(http, "evil.example.com/x")).exists is False  # never builds a hostile host
    with pytest.raises(BoardNotFound):
        await Recruitee().fetch(http, "Bad_Slug")


async def test_probe_existing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"offers": []}))
    assert (await Recruitee().probe(http, "bunq")).exists is True
