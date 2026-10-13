import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.gb import CONTENT_API, UkRegister, parse_csv

HEADER = "Organisation Name ,Town/City ,County,Type & Rating,Route\n"
ROWS = (
    '"  Acme Widgets Ltd",London,,Worker (A rating),Skilled Worker\n'
    '"Acme Widgets Ltd",London,,Worker (A rating),Global Business Mobility: Senior or Specialist Worker\n'
    '"Beta, Gamma & Sons Limited", ,Kent,Worker (A rating),Skilled Worker\n'
    ',London,,Worker (A rating),Skilled Worker\n'
)
CSV_URL = "https://assets.publishing.service.gov.uk/media/abc/2026-10-13_-_Worker_and_Temporary_Worker.csv"


def test_parse_csv_with_bom_and_padded_headers():
    records = parse_csv(("﻿" + HEADER + ROWS).encode("utf-8"))
    assert [r.legal_name for r in records] == ["Acme Widgets Ltd", "Acme Widgets Ltd", "Beta, Gamma & Sons Limited"]
    first = records[0]
    assert (first.country, first.source, first.evidence, first.city, first.route) == (
        "GB", "gb", "licence", "London", "Skilled Worker")
    assert records[2].city is None


def test_parse_csv_cp1252():
    data = (HEADER + '"Café Rouge Ltd",London,,Worker (A rating),Skilled Worker\n').encode("cp1252")
    assert parse_csv(data)[0].legal_name == "Café Rouge Ltd"


def test_parse_csv_missing_column_is_format_error():
    with pytest.raises(RegisterFormatError):
        parse_csv(b"Name,City\nAcme,London\n")


async def test_latest_picks_csv_attachment(http, respx_mock):
    respx_mock.get(CONTENT_API).mock(return_value=httpx.Response(200, json={"details": {"attachments": [
        {"url": "https://assets.publishing.service.gov.uk/media/x/guidance.pdf"},
        {"url": CSV_URL},
    ]}}))
    assert await UkRegister().latest(http) == CSV_URL


async def test_latest_without_csv_is_format_error(http, respx_mock):
    respx_mock.get(CONTENT_API).mock(return_value=httpx.Response(200, json={"details": {"attachments": []}}))
    with pytest.raises(RegisterFormatError):
        await UkRegister().latest(http)


async def test_fetch_downloads_version_url(http, respx_mock):
    respx_mock.get(CSV_URL).mock(return_value=httpx.Response(200, content=(HEADER + ROWS).encode()))
    records = await UkRegister().fetch(http, CSV_URL)
    assert len(records) == 3


async def test_fetch_http_error_raises(http, respx_mock):
    respx_mock.get(CSV_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await UkRegister().fetch(http, CSV_URL)
