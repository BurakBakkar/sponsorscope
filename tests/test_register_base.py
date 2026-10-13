import httpx

from sponsorscope.registers.base import is_bot_challenge


def test_detects_cloudflare_challenge():
    assert is_bot_challenge(httpx.Response(403, headers={"cf-mitigated": "challenge"}, text="x"))
    assert is_bot_challenge(httpx.Response(403, text="<title>Just a moment...</title>"))
    assert not is_bot_challenge(httpx.Response(403, text="Forbidden"))
    assert not is_bot_challenge(httpx.Response(200, text="Just a moment"))
