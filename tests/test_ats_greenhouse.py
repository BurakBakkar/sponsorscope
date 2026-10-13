import html

import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound, infer_remote
from sponsorscope.ats.greenhouse import Greenhouse


def job(job_id, internal_id, content, location="London, UK"):
    return {"id": job_id, "internal_job_id": internal_id, "title": " Backend Engineer ",
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
            "location": {"name": location}, "content": content,
            "updated_at": "2026-10-02T10:00:00-04:00", "first_published": "2026-09-30T10:00:00-04:00"}


def mock_board(respx_mock, slug, response):
    return respx_mock.get(host="boards-api.greenhouse.io", path=f"/v1/boards/{slug}/jobs").mock(return_value=response)


async def test_parses_escaped_html_and_dedupes_internal_job(http, respx_mock):
    escaped = html.escape("<p>We <strong>offer</strong> visa sponsorship &amp; relocation.</p>")
    route = mock_board(respx_mock, "acme", httpx.Response(200, json={"jobs": [
        job(1, 100, escaped), job(2, 100, escaped), job(3, 101, None, location="Remote - US"),
    ]}))
    postings = await Greenhouse().fetch(http, "acme")
    assert route.calls.last.request.url.params["content"] == "true"
    assert [p.id for p in postings] == ["greenhouse:acme:1", "greenhouse:acme:3"]
    first = postings[0]
    assert first.title == "Backend Engineer"
    assert first.description == "We offer visa sponsorship & relocation."
    assert (first.location_raw, first.country, first.remote, first.posted_at) == ("London, UK", None, None, "2026-09-30")
    assert postings[1].description == "" and postings[1].remote == "remote"


async def test_missing_board_raises_board_not_found(http, respx_mock):
    mock_board(respx_mock, "nope", httpx.Response(404, json={"status": 404, "error": "Job not found"}))
    with pytest.raises(BoardNotFound):
        await Greenhouse().fetch(http, "nope")


async def test_server_error_raises_http_error(http, respx_mock):
    mock_board(respx_mock, "acme", httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await Greenhouse().fetch(http, "acme")


def test_infer_remote():
    assert infer_remote("Remote (UK)") == "remote"
    assert infer_remote("London - Hybrid") == "hybrid"
    assert infer_remote("London") is None
    assert infer_remote(None) is None


async def test_probe_reports_board_name(http, respx_mock):
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme").mock(
        return_value=httpx.Response(200, json={"name": "Acme Widgets", "content": ""}))
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/nope").mock(return_value=httpx.Response(404))
    gh = Greenhouse()
    assert gh.provides_name is True
    assert (await gh.probe(http, "acme")).name == "Acme Widgets"
    assert (await gh.probe(http, "nope")).exists is False


async def test_probe_server_error_raises(http, respx_mock):
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await Greenhouse().probe(http, "acme")
