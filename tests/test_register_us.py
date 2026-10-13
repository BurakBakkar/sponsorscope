import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.us import PAGE, UsRegister, parse_lca, pick_file
from tests.xlsx_fixtures import make_xlsx

PAGE_HTML = """<table><tr><td>LCA Programs (H-1B, H-1B1, E-3)</td>
<td><a href="https://www.dol.gov//media/LCA_Disclosure_Data_FY2026_Q3.xlsx">LCA_Dislclosure_Data_FY2026_Q3.xlsx</a></td></tr>
<tr><td><a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx">FY2025 Q4</a></td></tr>
<tr><td><a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q3.xlsx">FY2025 Q3</a></td></tr>
<tr><td><a href="/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY2025_Q4.xlsx">PERM</a></td></tr></table>"""
HEADER = ["CASE_NUMBER", "CASE_STATUS", "DECISION_DATE", "VISA_CLASS", "EMPLOYER_NAME", "EMPLOYER_COUNTRY"]


def test_pick_file_prefers_latest_complete_fiscal_year():
    url, period = pick_file(PAGE_HTML)
    assert url == "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx"
    assert period == "FY2025"


def test_pick_file_falls_back_to_newest_when_no_q4():
    url, period = pick_file(PAGE_HTML.replace("FY2025_Q4", "FY2025_Q2"))
    assert url.endswith("LCA_Disclosure_Data_FY2026_Q3.xlsx") and period == "FY2026"
    with pytest.raises(RegisterFormatError):
        pick_file("<a href='/other.xlsx'>x</a>")


def test_parse_lca_counts_certified_h1b_per_normalised_employer():
    data = make_xlsx([HEADER,
        ["I-1", "Certified", "2025-10-01", "H-1B", "Acme Widgets LLC", "UNITED STATES OF AMERICA"],
        ["I-2", "Certified", "2025-10-02", "H-1B", "ACME WIDGETS, LLC", "UNITED STATES OF AMERICA"],
        ["I-3", "Certified", "2025-10-03", "H-1B", "Acme Widgets LLC", "UNITED STATES OF AMERICA"],
        ["I-4", "Certified - Withdrawn", "2025-10-04", "H-1B", "Acme Widgets LLC", ""],
        ["I-5", "Denied", "2025-10-05", "H-1B", "Beta Corp", ""],
        ["I-6", "Certified", "2025-10-06", "E-3 Australian", "Beta Corp", ""],
        ["I-7", "Certified", "2025-10-07", "H-1B", "Gamma Inc", ""]])
    records = {r.legal_name: r for r in parse_lca(data, "FY2025")}
    assert set(records) == {"Acme Widgets LLC", "Gamma Inc"}
    acme = records["Acme Widgets LLC"]
    assert (acme.country, acme.source, acme.evidence, acme.route, acme.filings, acme.period) == (
        "US", "us", "history", "H-1B", 3, "FY2025")


def test_parse_lca_missing_columns():
    with pytest.raises(RegisterFormatError):
        parse_lca(make_xlsx([["CASE_NUMBER", "EMPLOYER"]]), "FY2025")


async def test_latest_and_fetch(http, respx_mock):
    respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=PAGE_HTML))
    url = "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx"
    respx_mock.get(url).mock(return_value=httpx.Response(200, content=make_xlsx([HEADER,
        ["I-1", "Certified", "d", "H-1B", "Gamma Inc", ""]])))
    reg = UsRegister()
    version = await reg.latest(http)
    assert version == url
    [record] = await reg.fetch(http, version)
    assert (record.legal_name, record.filings, record.period) == ("Gamma Inc", 1, "FY2025")
