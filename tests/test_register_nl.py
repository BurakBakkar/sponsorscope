import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.nl import PAGE, NlRegister, parse_page

HTML = """<html><head><meta name="dcterms.modified" content="2026-10-05"></head><body>
<p>The overview was last updated on 5 October 2026.</p>
<div class="ind-table-wrapper"><table>
<thead><tr><th scope="col">Organisation</th><th scope="col">KVK (Chamber of Commerce) number</th></tr></thead>
<tbody>
<tr><th scope="row">""Aa-Dee"" Machinefabriek en Staalbouw Nederland B.V.</th><td>16051874</td></tr>
<tr><th scope="row">Booking.com B.V.</th><td>01041354</td></tr>
<tr><th scope="row">JETRO Amsterdam</th><td></td></tr>
<tr><th scope="row">  </th><td>123</td></tr>
</tbody></table></div></body></html>"""


def test_parse_page():
    version, records = parse_page(HTML)
    assert version == "5 October 2026"
    assert [r.legal_name for r in records] == [
        '"Aa-Dee" Machinefabriek en Staalbouw Nederland B.V.', "Booking.com B.V.", "JETRO Amsterdam"]
    assert records[1].registry_id == "01041354" and records[2].registry_id is None
    assert {(r.country, r.source, r.evidence, r.route) for r in records} == {("NL", "nl", "licence", "Work")}


def test_parse_page_format_errors():
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("last updated on", "refreshed"))
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("<th scope=\"col\">Organisation</th>", "<th>Name</th>"))


async def test_latest_then_fetch_uses_one_request(http, respx_mock):
    route = respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=HTML))
    reg = NlRegister()
    version = await reg.latest(http)
    assert len(await reg.fetch(http, version)) == 3
    assert route.call_count == 1
