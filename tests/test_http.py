import httpx
import pytest

from sponsorscope.http import USER_AGENT, Http

URL = "https://example.test/a"


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
async def recording_http(sleeps):
    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    client = Http(sleep=record, rate=1e6)
    yield client
    await client.aclose()


async def test_sends_user_agent(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200))
    await http.get(URL)
    assert route.calls.last.request.headers["User-Agent"] == USER_AGENT
    assert USER_AGENT.startswith("sponsorscope/")


async def test_retries_5xx_then_succeeds(http, respx_mock):
    route = respx_mock.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, text="ok")])
    resp = await http.get(URL)
    assert resp.status_code == 200 and route.call_count == 2


async def test_gives_up_after_retries_and_returns_last_response(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(503))
    resp = await http.get(URL)
    assert resp.status_code == 503 and route.call_count == 5  # 1 try + 4 retries


async def test_does_not_retry_404(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(404))
    resp = await http.get(URL)
    assert resp.status_code == 404 and route.call_count == 1


async def test_honours_numeric_retry_after(recording_http, sleeps, respx_mock):
    respx_mock.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    await recording_http.get(URL)
    assert 7.0 in sleeps


async def test_http_date_retry_after_in_past_means_no_wait(recording_http, sleeps, respx_mock):
    respx_mock.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"}), httpx.Response(200)]
    )
    await recording_http.get(URL)
    assert 0.0 in sleeps


async def test_retry_after_is_capped(recording_http, sleeps, respx_mock):
    respx_mock.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "99999"}), httpx.Response(200)])
    await recording_http.get(URL)
    assert max(sleeps) <= 300.0


async def test_retries_transport_errors(http, respx_mock):
    route = respx_mock.get(URL).mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200)])
    resp = await http.get(URL)
    assert resp.status_code == 200 and route.call_count == 2


async def test_raises_after_persistent_transport_errors(http, respx_mock):
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(httpx.TransportError):
        await http.get(URL)
