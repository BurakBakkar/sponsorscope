from datetime import date

import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.ie import STATS_PAGE, IeRegister, find_file, parse_permits, pick_year_page
from tests.xlsx_fixtures import make_xlsx

STATS_HTML = """<ul>
<li><a href="/en/publications/employment-permit-statistics-2026.html">Employment Permit Statistics for 2026</a></li>
<li><a href="/en/publications/employment-permit-statistics-2025.html">2025</a></li>
<li><a href="/en/Publications/Employment-Permit-Statisitcs-2013.html">2013</a></li></ul>"""
YEAR_HTML = """<div class="relatedDocument"><a href="/en/publications/publication-files/employment-permits-issued-to-companies-2025.xlsx">
Employment permits issued to companies 2025</a></div>"""
PERMITS = [["Employer Name", "Permits Issued Jan", "Permits Issued Feb", "Permits Issued Grand Total"],
           ["24 Doc (Doctor On Call) Limited", 1.0, 2.0, 3.0],
           ["Acme Widgets Ltd", "", 1.0, 1.0],
           ["ACME WIDGETS LIMITED", 2.0, "", 2.0],
           ["Total", 3.0, 3.0, 6.0]]


def test_pick_year_page_uses_last_complete_year():
    url, year = pick_year_page(STATS_HTML, date(2026, 10, 13))
    assert (url, year) == ("https://enterprise.gov.ie/en/publications/employment-permit-statistics-2025.html", 2025)
    with pytest.raises(RegisterFormatError):
        pick_year_page("<a href='/x.html'>x</a>", date(2026, 10, 13))


def test_find_file():
    page = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-2025.html"
    assert find_file(YEAR_HTML, page) == (
        "https://enterprise.gov.ie/en/publications/publication-files/employment-permits-issued-to-companies-2025.xlsx")


def test_parse_permits_skips_total_and_aggregates():
    records = {r.legal_name: r for r in parse_permits(make_xlsx(PERMITS, sheet="Export"), "2025")}
    assert set(records) == {"24 Doc (Doctor On Call) Limited", "Acme Widgets Ltd"}
    acme = records["Acme Widgets Ltd"]
    assert (acme.country, acme.evidence, acme.filings, acme.period, acme.route) == ("IE", "history", 3, "2025", "Employment permit")


def test_parse_permits_unexpected_header():
    with pytest.raises(RegisterFormatError):
        parse_permits(make_xlsx([["Company", "Count"]]), "2025")


async def test_latest_and_fetch(http, respx_mock):
    year_url = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-2025.html"
    file_url = "https://enterprise.gov.ie/en/publications/publication-files/employment-permits-issued-to-companies-2025.xlsx"
    respx_mock.get(STATS_PAGE).mock(return_value=httpx.Response(200, text=STATS_HTML))
    respx_mock.get(year_url).mock(return_value=httpx.Response(200, text=YEAR_HTML))
    respx_mock.get(file_url).mock(return_value=httpx.Response(200, content=make_xlsx(PERMITS)))
    reg = IeRegister(today=lambda: date(2026, 10, 13))
    assert await reg.latest(http) == file_url
    assert {r.period for r in await reg.fetch(http, file_url)} == {"2025"}


def test_parse_permits_2025_layout_blank_header_and_grand_total_row():
    rows = [["", "January", "February", "Grand Total"],
            ["Grand Total", 3798.0, 2994.0, 31044.0],
            [" IQVIA RDS IRELAND LTD", "", 2.0, 2.0],
            ["Zyntrica Technologies Limited", "", 1.0, 1.0]]
    records = {r.legal_name: r.filings for r in parse_permits(make_xlsx(rows), "2025")}
    assert records == {"IQVIA RDS IRELAND LTD": 2, "Zyntrica Technologies Limited": 1}
