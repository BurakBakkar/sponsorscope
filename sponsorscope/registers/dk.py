from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError

PAGE = "https://www.nyidanmark.dk/en-GB/Words-and-concepts/SIRI/Certified-companies"
_UPDATED = re.compile(r"Last updated (\d{2}-\d{2}-\d{4})")
_HEADER = ["Name of company", "CVR no."]


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_page(html: str) -> tuple[str, list[SponsorRecord]]:
    tree = LexborHTMLParser(html)
    match = _UPDATED.search(tree.body.text() if tree.body else "")
    if match is None:
        raise RegisterFormatError("DK register: 'Last updated' date not found")
    table = tree.css_first("div.rich-text-editor table") or tree.css_first("table")
    rows = [[_clean(c.text()) for c in r.css("td") or r.css("th")] for r in table.css("tr")] if table else []
    if not rows or rows[0][:2] != _HEADER:
        raise RegisterFormatError(f"DK register: unexpected header {rows[0] if rows else None}")
    records = [
        SponsorRecord(country="DK", source="dk", evidence="licence", legal_name=r[0],
                      registry_id=(r[1] or None) if len(r) > 1 else None, route="Fast-track")
        for r in rows[1:] if r and r[0]
    ]
    return match.group(1), records


class DkRegister:
    """SIRI certified companies (Fast-track scheme). Danish sort order puts 'Aa…' last; irrelevant here."""

    name = "dk"

    def __init__(self) -> None:
        self._cache: tuple[str, list[SponsorRecord]] | None = None

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        resp.raise_for_status()
        self._cache = parse_page(resp.text)
        return self._cache[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        if self._cache is None or self._cache[0] != version:
            await self.latest(http)
        return self._cache[1]
