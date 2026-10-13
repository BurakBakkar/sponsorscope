from __future__ import annotations

import csv
import io

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError

CONTENT_API = "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
NAME_COL, CITY_COL, ROUTE_COL = "Organisation Name", "Town/City", "Route"


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_csv(data: bytes) -> list[SponsorRecord]:
    reader = csv.DictReader(io.StringIO(_decode(data)))
    if reader.fieldnames is None:
        raise RegisterFormatError("UK register CSV is empty")
    reader.fieldnames = [f.strip() for f in reader.fieldnames]
    missing = {NAME_COL, CITY_COL, ROUTE_COL} - set(reader.fieldnames)
    if missing:
        raise RegisterFormatError(f"UK register CSV missing columns: {sorted(missing)}")
    records = []
    for row in reader:
        name = _clean(row.get(NAME_COL))
        if name is None:
            continue
        records.append(SponsorRecord(country="GB", source="gb", evidence="licence", legal_name=name,
                                     city=_clean(row.get(CITY_COL)), route=_clean(row.get(ROUTE_COL))))
    return records


class UkRegister:
    """Home Office Register of licensed sponsors: workers (OGL v3.0)."""

    name = "gb"

    async def latest(self, http: Http) -> str:
        resp = await http.get(CONTENT_API)
        resp.raise_for_status()
        for attachment in resp.json().get("details", {}).get("attachments", []):
            url = attachment.get("url", "")
            if url.lower().endswith(".csv"):
                return url
        raise RegisterFormatError("no CSV attachment in GOV.UK content API response")

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)
        resp.raise_for_status()
        return parse_csv(resp.content)
