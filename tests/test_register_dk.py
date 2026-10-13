import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.dk import PAGE, DkRegister, parse_page

HTML = """<html><body><div class="rich-text-editor"><table width="614">
<tr><td class="xl65"><p class="bodycopy-small">Name of company</p></td><td><p class="bodycopy-small">CVR no.</p></td></tr>
<tr><td class="xl66"><p class="bodycopy-small">
   &amp;TRADITION A/S</p></td><td><p class="bodycopy-small">18169304</p></td></tr>
<tr><td><p class="bodycopy-small">3Shape A/S&nbsp;</p></td><td><p class="bodycopy-small">25553489&nbsp;</p></td></tr>
<tr><td><p class="bodycopy-small">&nbsp;</p></td><td><p class="bodycopy-small"></p></td></tr>
<tr><td><p class="bodycopy-small">Aarhus Universitet</p></td><td><p class="bodycopy-small">31119103</p></td></tr>
</table></div>
<p class="byline bodycopy-small white"> Last updated 12-10-2026 - Published by: SIRI </p></body></html>"""


def test_parse_page():
    version, records = parse_page(HTML)
    assert version == "12-10-2026"
    assert [(r.legal_name, r.registry_id) for r in records] == [
        ("&TRADITION A/S", "18169304"), ("3Shape A/S", "25553489"), ("Aarhus Universitet", "31119103")]
    assert {(r.country, r.evidence, r.route) for r in records} == {("DK", "licence", "Fast-track")}


def test_format_errors():
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("Name of company", "Firm"))
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("Last updated", "Updated"))


async def test_latest_then_fetch(http, respx_mock):
    route = respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=HTML))
    reg = DkRegister()
    assert len(await reg.fetch(http, await reg.latest(http))) == 3 and route.call_count == 1
