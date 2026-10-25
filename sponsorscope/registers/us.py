from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import HISTORY_SHRINK_RATIO, RegisterFormatError
from sponsorscope.registers.xlsx import cell_str, sheet_rows

PAGE = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
_FILE = re.compile(r"LCA_Disclosure_Data_FY(\d{4})_Q(\d)\.xlsx$", re.IGNORECASE)  # match hrefs: link text has typos
_REQUIRED = ("CASE_NUMBER", "CASE_STATUS", "VISA_CLASS", "EMPLOYER_NAME")
NAICS = "NAICS_CODE"  # optional column
PARSER_REV = "#naics"  # appended to the version: changing it makes the next run re-read the year's files


def _url_period(url: str) -> str:
    match = _FILE.search(url)
    if match is None:
        raise RegisterFormatError(f"US LCA: cannot read fiscal year from {url}")
    return f"FY{match.group(1)}"


def pick_files(html: str) -> tuple[list[str], str]:
    """Every quarterly file of the newest fiscal year that has a Q4 file (else the newest year).

    Q1–Q3 files are year-to-date but the Q4 file holds only Jul–Sep, so a whole fiscal year
    needs all of them; parse_lca de-duplicates case numbers across files.
    """
    files: dict[tuple[int, int], str] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").split("?")[0]
        match = _FILE.search(href)
        if match:
            files[(int(match.group(1)), int(match.group(2)))] = urljoin(PAGE, href).replace("gov//", "gov/")
    if not files:
        raise RegisterFormatError("US LCA: no LCA_Disclosure_Data_FY*_Q*.xlsx link on the performance page")
    complete_years = [fy for fy, q in files if q == 4]
    year = max(complete_years) if complete_years else max(fy for fy, _ in files)
    return [files[key] for key in sorted(k for k in files if k[0] == year)], f"FY{year}"


Case = tuple[bool, str, str]  # (counted, employer name, NAICS code)


def _collect_cases(data: bytes, cases: dict[str, Case]) -> None:
    rows = sheet_rows(data)
    header = [cell_str(h) for h in next(rows, [])]
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in _REQUIRED if c not in idx]
    if missing:
        raise RegisterFormatError(f"US LCA: missing columns {missing}")
    case_i, status_i, visa_i, name_i = (idx[c] for c in _REQUIRED)
    naics_i = idx.get(NAICS)
    width = max(case_i, status_i, visa_i, name_i)
    for row in rows:
        if len(row) <= width:
            continue
        counted = cell_str(row[status_i]) == "Certified" and cell_str(row[visa_i]) == "H-1B"
        naics = cell_str(row[naics_i]) if naics_i is not None and naics_i < len(row) else ""
        cases[cell_str(row[case_i])] = (counted, cell_str(row[name_i]), naics.split(".")[0])  # later files win


def _aggregate(cases: dict[str, Case], period: str) -> list[SponsorRecord]:
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    codes: dict[str, Counter[str]] = {}
    for counted, raw, naics in cases.values():
        norm = normalize(raw) if counted else ""
        if not norm:
            continue
        filings[norm] += 1
        spellings.setdefault(norm, Counter())[raw] += 1
        if naics:
            codes.setdefault(norm, Counter())[naics] += 1
    return [
        SponsorRecord(country="US", source="us", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="H-1B", filings=count, period=period,
                      naics=codes[n].most_common(1)[0][0] if n in codes else None)
        for n, count in filings.items()
    ]


def parse_lca(files: Iterable[bytes], period: str) -> list[SponsorRecord]:
    """Certified H-1B LCAs per normalised employer; a case number seen again in a later file wins."""
    cases: dict[str, Case] = {}
    for data in files:
        _collect_cases(data, cases)
    return _aggregate(cases, period)


class UsRegister:
    """DOL OFLC LCA disclosure data: certified H-1B LCAs per employer over the last complete fiscal year."""

    name = "us"
    shrink_ratio = HISTORY_SHRINK_RATIO

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        resp.raise_for_status()
        return " ".join(pick_files(resp.text)[0]) + f" {PARSER_REV}"  # version = the year's file URLs

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        urls = [u for u in version.split() if not u.startswith("#")]
        cases: dict[str, Case] = {}
        for url in urls:  # one 80–250 MB file in memory at a time; only when the version changes
            resp = await http.get(url)
            resp.raise_for_status()
            _collect_cases(resp.content, cases)
            del resp
        return _aggregate(cases, _url_period(urls[-1]))
