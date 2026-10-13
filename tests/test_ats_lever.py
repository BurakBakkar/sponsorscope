import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.lever import Lever

POSTING = {
    "id": "abc-123", "text": "Data Engineer", "hostedUrl": "https://jobs.lever.co/acme/abc-123",
    "categories": {"location": "Amsterdam", "team": "Data"}, "country": "nl", "workplaceType": "hybrid",
    "createdAt": 1727690400000, "descriptionPlain": "Join our data team.",
    "lists": [{"text": "Requirements", "content": "<li>Fluent Dutch</li><li>Python</li>"}],
    "additionalPlain": "We offer visa sponsorship.",
}


def mock_host(respx_mock, host, slug, response):
    return respx_mock.get(host=host, path=f"/v0/postings/{slug}").mock(return_value=response)


async def test_parses_posting(http, respx_mock):
    route = mock_host(respx_mock, "api.lever.co", "acme", httpx.Response(200, json=[POSTING]))
    [p] = await Lever().fetch(http, "acme")
    assert route.calls.last.request.url.params["mode"] == "json"
    assert p.id == "lever:acme:abc-123"
    assert (p.title, p.country, p.remote, p.location_raw, p.posted_at) == (
        "Data Engineer", "NL", "hybrid", "Amsterdam", "2024-09-30")
    assert "Join our data team." in p.description
    assert "Requirements" in p.description and "Fluent Dutch" in p.description
    assert p.description.endswith("We offer visa sponsorship.")


async def test_falls_back_to_eu_host(http, respx_mock):
    mock_host(respx_mock, "api.lever.co", "euco", httpx.Response(404, json={"ok": False}))
    mock_host(respx_mock, "api.eu.lever.co", "euco", httpx.Response(200, json=[POSTING]))
    assert len(await Lever().fetch(http, "euco")) == 1


async def test_missing_on_both_hosts_raises_board_not_found(http, respx_mock):
    mock_host(respx_mock, "api.lever.co", "nope", httpx.Response(404))
    mock_host(respx_mock, "api.eu.lever.co", "nope", httpx.Response(404))
    with pytest.raises(BoardNotFound):
        await Lever().fetch(http, "nope")


async def test_null_country_and_unspecified_workplace(http, respx_mock):
    posting = {**POSTING, "country": None, "workplaceType": "unspecified", "categories": {"location": "Remote"}}
    mock_host(respx_mock, "api.lever.co", "acme", httpx.Response(200, json=[posting]))
    [p] = await Lever().fetch(http, "acme")
    assert p.country is None and p.remote == "remote"
