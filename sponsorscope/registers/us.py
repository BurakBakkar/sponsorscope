from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.xlsx import cell_str, sheet_rows

PAGE = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
_FILE = re.compile(r"LCA_Disclosure_Data_FY(\d{4})_Q(\d)\.xlsx$", re.IGNORECASE)  # match hrefs: link text has typos
_REQUIRED = ("CASE_STATUS", "VISA_CLASS", "EMPLOYER_NAME")


def _url_period(url: str) -> str:
    match = _FILE.search(url)
    if match is None:
        raise RegisterFormatError(f"US LCA: cannot read fiscal year from {url}")
    return f"FY{match.group(1)}"


def pick_file(html: str) -> tuple[str, str]:
    """Newest fiscal year with a Q4 (complete) file; otherwise the newest file of any quarter."""
    files: dict[tuple[int, int], str] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").split("?")[0]
        match = _FILE.search(href)
        if match:
            files[(int(match.group(1)), int(match.group(2)))] = urljoin(PAGE, href).replace("gov//", "gov/")
    if not files:
        raise RegisterFormatError("US LCA: no LCA_Disclosure_Data_FY*_Q*.xlsx link on the performance page")
    complete = [key for key in files if key[1] == 4]
    key = max(complete) if complete else max(files)
    return files[key], f"FY{key[0]}"


def parse_lca(data: bytes, period: str) -> list[SponsorRecord]:
    rows = sheet_rows(data)
    header = [cell_str(h) for h in next(rows, [])]
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in _REQUIRED if c not in idx]
    if missing:
        raise RegisterFormatError(f"US LCA: missing columns {missing}")
    status_i, visa_i, name_i = (idx[c] for c in _REQUIRED)
    width = max(status_i, visa_i, name_i)
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for row in rows:
        if len(row) <= width or cell_str(row[status_i]) != "Certified" or cell_str(row[visa_i]) != "H-1B":
            continue
        raw = cell_str(row[name_i])
        norm = normalize(raw)
        if not norm:
            continue
        filings[norm] += 1
        spellings.setdefault(norm, Counter())[raw] += 1
    return [
        SponsorRecord(country="US", source="us", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="H-1B", filings=count, period=period)
        for n, count in filings.items()
    ]


class UsRegister:
    """DOL OFLC LCA disclosure data: certified H-1B LCAs per employer for the last complete fiscal year."""

    name = "us"

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        resp.raise_for_status()
        return pick_file(resp.text)[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)  # 80–250 MB; only downloaded when the version (file URL) changes
        resp.raise_for_status()
        return parse_lca(resp.content, _url_period(version))
