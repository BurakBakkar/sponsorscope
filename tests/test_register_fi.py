import httpx
import pytest

from sponsorscope.registers.base import RegisterBlocked, RegisterFormatError
from sponsorscope.registers.fi import PAGE, FiRegister, parse_page

# Columns as reported for migri.fi (unverified live: the site serves a bot challenge).
HTML = """<html><body><table>
<tr><th>Employer</th><th>Business ID</th><th>Certificate issued</th><th>Valid until</th></tr>
<tr><td>Hansavest Työvoima Oy</td><td>2788957-5</td><td>8 March 2023</td><td>8 March 2028</td></tr>
<tr><td>Wolt Enterprises Oy</td><td>2646674-9</td><td>1 June 2024</td><td>1 June 2029</td></tr>
</table></body></html>"""


def test_parse_page_by_header_names():
    version, records = parse_page(HTML)
    assert [(r.legal_name, r.registry_id) for r in records] == [
        ("Hansavest Työvoima Oy", "2788957-5"), ("Wolt Enterprises Oy", "2646674-9")]
    assert len(version) == 16 and parse_page(HTML)[0] == version  # content hash: stable
    assert {(r.country, r.evidence) for r in records} == {("FI", "licence")}


def test_parse_page_without_business_id_table():
    with pytest.raises(RegisterFormatError):
        parse_page("<table><tr><th>Name</th></tr></table>")


async def test_bot_challenge_raises_blocked(http, respx_mock):
    respx_mock.get(PAGE).mock(return_value=httpx.Response(
        403, headers={"cf-mitigated": "challenge"}, text="<title>Just a moment...</title>"))
    with pytest.raises(RegisterBlocked):
        await FiRegister().latest(http)


async def test_reachable_page_parses(http, respx_mock):
    respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=HTML))
    reg = FiRegister()
    assert len(await reg.fetch(http, await reg.latest(http))) == 2
