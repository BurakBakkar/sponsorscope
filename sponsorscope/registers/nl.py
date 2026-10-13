from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError

PAGE = "https://ind.nl/en/public-register-recognised-sponsors/public-register-work"
_UPDATED = re.compile(r"last updated on (\d{1,2} \w+ \d{4})", re.IGNORECASE)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_page(html: str) -> tuple[str, list[SponsorRecord]]:
    tree = LexborHTMLParser(html)
    match = _UPDATED.search(tree.body.text() if tree.body else "")
    if match is None:
        raise RegisterFormatError("NL register: 'last updated on' date not found")
    table = tree.css_first("div.ind-table-wrapper > table") or tree.css_first("table")
    headers = [_clean(h.text()) for h in table.css("thead th")] if table else []
    if not headers or headers[0] != "Organisation":
        raise RegisterFormatError(f"NL register: unexpected table headers {headers}")
    records = []
    for row in table.css("tbody tr"):
        name_cell, kvk_cell = row.css_first("th"), row.css_first("td")
        name = _clean(name_cell.text() if name_cell else "").replace('""', '"')
        if not name:
            continue
        kvk = _clean(kvk_cell.text() if kvk_cell else "")
        records.append(SponsorRecord(country="NL", source="nl", evidence="licence", legal_name=name,
                                     registry_id=kvk or None, route="Work"))
    return match.group(1), records


class NlRegister:
    """IND public register of recognised sponsors, 'Work' (labour and highly skilled migrants)."""

    name = "nl"

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
