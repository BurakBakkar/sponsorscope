from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import date
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.xlsx import cell_int, cell_str, sheet_rows

STATS_PAGE = "https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/statistics/"
_YEAR_PAGE = re.compile(r"employment-permit-statistics-(\d{4})\.html", re.IGNORECASE)
_FILE_YEAR = re.compile(r"issued-to-companies-(\d{4})", re.IGNORECASE)


def pick_year_page(html: str, today: date) -> tuple[str, int]:
    """Newest year before the current one (the current year's file is year-to-date)."""
    pages: dict[int, str] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = a.attributes.get("href") or ""
        match = _YEAR_PAGE.search(href)
        if match:
            pages[int(match.group(1))] = urljoin(STATS_PAGE, href)
    if not pages:
        raise RegisterFormatError("IE permits: no yearly statistics pages linked")
    complete = [y for y in pages if y < today.year]
    year = max(complete) if complete else max(pages)
    return pages[year], year


def find_file(html: str, page_url: str) -> str:
    tree = LexborHTMLParser(html)
    link = tree.css_first('div.relatedDocument a[href*="issued-to-companies"]') or \
        tree.css_first('a[href*="issued-to-companies"]')
    if link is None:
        raise RegisterFormatError(f"IE permits: no 'issued-to-companies' file on {page_url}")
    return urljoin(page_url, link.attributes.get("href") or "")


def parse_permits(data: bytes, period: str) -> list[SponsorRecord]:
    rows = sheet_rows(data)
    header = [cell_str(h) for h in next(rows, [])]
    # 2026 files: "Employer Name" … "Permits Issued Grand Total", "Total" footer row;
    # 2025 files: blank first header, full month names, "Grand Total" row first.
    if not header or header[0] not in ("Employer Name", "") or not header[-1].endswith("Grand Total"):
        raise RegisterFormatError(f"IE permits: unexpected header {header[:2]}…")
    total_i = len(header) - 1
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for row in rows:
        raw = cell_str(row[0]) if row else ""
        if raw in ("", "Total", "Grand Total") or len(row) <= total_i:
            continue
        norm = normalize(raw)
        if not norm:
            continue
        filings[norm] += cell_int(row[total_i])
        spellings.setdefault(norm, Counter())[raw] += 1
    return [
        SponsorRecord(country="IE", source="ie", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="Employment permit", filings=count, period=period)
        for n, count in filings.items()
    ]


class IeRegister:
    """DETE employment permits issued to companies (last complete calendar year)."""

    name = "ie"

    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self._today = today

    async def latest(self, http: Http) -> str:
        stats = await http.get(STATS_PAGE)
        stats.raise_for_status()
        page_url, _year = pick_year_page(stats.text, self._today())
        page = await http.get(page_url)
        page.raise_for_status()
        return find_file(page.text, page_url)

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)
        resp.raise_for_status()
        match = _FILE_YEAR.search(version)
        return parse_permits(resp.content, match.group(1) if match else "latest year")
