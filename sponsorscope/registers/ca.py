from __future__ import annotations

import re
from collections import Counter

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import HISTORY_SHRINK_RATIO, RegisterFormatError
from sponsorscope.registers.xlsx import cell_int, cell_str, sheet_rows

PACKAGE_API = "https://open.canada.ca/data/api/action/package_show?id=90fed587-1364-4f33-a9ee-208181dc0b97"
_NAME_QUARTER = re.compile(r"^(\d{4})Q(\d)-")
_URL_QUARTER = re.compile(r"tfwp_(\d{4})q(\d)_pos_en\.xlsx", re.IGNORECASE)
_HEADER_START = ["Province/Territory", "Program Stream", "Employer"]


def pick_resource(package: dict) -> tuple[str, str]:
    best: tuple[tuple[int, int], str] | None = None
    for res in (package.get("result") or {}).get("resources", []):
        language = res.get("language")
        if (res.get("format") or "").upper() != "XLSX" or language not in (["en"], "en"):
            continue
        match = _NAME_QUARTER.match(res.get("name") or "") or _URL_QUARTER.search(res.get("url") or "")
        if match:
            key = (int(match.group(1)), int(match.group(2)))
            if best is None or key > best[0]:
                best = (key, res["url"])
    if best is None:
        raise RegisterFormatError("CA LMIA: no English XLSX quarterly resource in the CKAN package")
    return best[1], f"{best[0][0]} Q{best[0][1]}"


def _url_period(url: str) -> str:
    match = _URL_QUARTER.search(url)
    return f"{match.group(1)} Q{match.group(2)}" if match else "latest quarter"


def parse_lmia(data: bytes, period: str) -> list[SponsorRecord]:
    rows = list(sheet_rows(data))
    header_at = next((i for i, r in enumerate(rows[:10]) if [cell_str(c) for c in r[:3]] == _HEADER_START), None)
    if header_at is None:
        raise RegisterFormatError("CA LMIA: header row not found in the first 10 rows")
    idx = {cell_str(h): i for i, h in enumerate(rows[header_at])}
    if "Approved LMIAs" not in idx:
        raise RegisterFormatError("CA LMIA: 'Approved LMIAs' column missing")
    name_i, count_i = idx["Employer"], idx["Approved LMIAs"]
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for row in rows[header_at + 1:]:
        if row and cell_str(row[0]).startswith("Notes"):
            break
        if len(row) <= max(name_i, count_i):
            continue
        raw = cell_str(row[name_i])
        norm = normalize(raw)
        if not norm:
            continue
        filings[norm] += cell_int(row[count_i]) or 1
        spellings.setdefault(norm, Counter())[raw] += 1
    return [
        SponsorRecord(country="CA", source="ca", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="LMIA", filings=count, period=period)
        for n, count in filings.items()
    ]


class CaRegister:
    """ESDC positive LMIA employers list (newest quarter; quarters are not cumulative)."""

    name = "ca"
    shrink_ratio = HISTORY_SHRINK_RATIO

    async def latest(self, http: Http) -> str:
        resp = await http.get(PACKAGE_API)
        resp.raise_for_status()
        return pick_resource(resp.json())[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)
        resp.raise_for_status()
        return parse_lmia(resp.content, _url_period(version))
