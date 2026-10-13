import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.ca import PACKAGE_API, CaRegister, parse_lmia, pick_resource
from tests.xlsx_fixtures import make_xlsx

BASE = "https://open.canada.ca/data/dataset/90fed587/resource"
PACKAGE = {"result": {"metadata_modified": "2026-07-22T13:31:33", "resources": [
    {"name": "2025Q4-Employers Who Were Issued a Positive LMIA", "format": "XLSX", "language": ["en"],
     "url": f"{BASE}/a/download/tfwp_2025q4_pos_en.xlsx"},
    {"name": "2026Q1-Employers Who Were Issued a Positive LMIA", "format": "XLSX", "language": ["en"],
     "url": f"{BASE}/b/download/tfwp_2026q1_pos_en.xlsx"},
    {"name": "2026T1-Employeurs", "format": "XLSX", "language": ["fr"], "url": f"{BASE}/c/download/tfwp_2026q1_pos_fr.xlsx"},
    {"name": "2026Q1-Employers (CSV)", "format": "CSV", "language": ["en"], "url": f"{BASE}/d/download/x.csv"},
]}}
HEADER = ["Province/Territory", "Program Stream", "Employer", "Address", "Occupation", "Incorporate Status",
          "Approved LMIAs", "Approved Positions"]


def lmia_rows():
    return [["Positive Labour Market Impact Assessment (LMIA) Employers List, 2026 Q1"], HEADER,
            ["Ontario   ", "High Wage   ", "Acme Software Inc.", "Toronto, ON", "21231-Software engineers", "Yes", 2.0, 3.0],
            ["Ontario", "Global Talent Stream", "ACME SOFTWARE INC", "Toronto, ON", "21231", "Yes", 1.0, 1.0],
            ["Quebec", "Low Wage", "Boulangerie Ltée", "Montréal, QC", "65201", "Unknown", 1.0, 4.0],
            ["", "", "", "", "", "", "", ""],
            ["Notes:"], ["1. Employers with personal names are excluded."]]


def test_pick_resource_newest_english_xlsx():
    assert pick_resource(PACKAGE) == (f"{BASE}/b/download/tfwp_2026q1_pos_en.xlsx", "2026 Q1")
    with pytest.raises(RegisterFormatError):
        pick_resource({"result": {"resources": []}})


def test_parse_lmia_header_on_second_row_and_notes_footer():
    records = {r.legal_name: r for r in parse_lmia(make_xlsx(lmia_rows()), "2026 Q1")}
    assert set(records) == {"Acme Software Inc.", "Boulangerie Ltée"}
    acme = records["Acme Software Inc."]
    assert (acme.country, acme.evidence, acme.filings, acme.period, acme.route) == ("CA", "history", 3, "2026 Q1", "LMIA")


def test_parse_lmia_without_header():
    with pytest.raises(RegisterFormatError):
        parse_lmia(make_xlsx([["title"], ["Employer", "Count"]]), "2026 Q1")


async def test_latest_and_fetch(http, respx_mock):
    respx_mock.get(PACKAGE_API).mock(return_value=httpx.Response(200, json=PACKAGE))
    url = f"{BASE}/b/download/tfwp_2026q1_pos_en.xlsx"
    respx_mock.get(url).mock(return_value=httpx.Response(200, content=make_xlsx(lmia_rows())))
    reg = CaRegister()
    assert await reg.latest(http) == url
    assert len(await reg.fetch(http, url)) == 2
