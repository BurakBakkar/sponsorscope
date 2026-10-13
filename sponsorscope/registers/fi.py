from __future__ import annotations

import hashlib
import re

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterBlocked, RegisterFormatError, is_bot_challenge

PAGE = "https://migri.fi/en/certified-employers"
_ID_HEADER = re.compile(r"business id|y-tunnus", re.IGNORECASE)
_NAME_HEADER = re.compile(r"employer|name|työnantaja", re.IGNORECASE)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_page(html: str) -> tuple[str, list[SponsorRecord]]:
    """Header-driven parse (column order on migri.fi is unverified). Version = content hash."""
    tree = LexborHTMLParser(html)
    for table in tree.css("table"):
        rows = [[_clean(c.text()) for c in r.css("th, td")] for r in table.css("tr")]
        if not rows:
            continue
        header = rows[0]
        id_col = next((i for i, h in enumerate(header) if _ID_HEADER.search(h)), None)
        if id_col is None:
            continue
        name_col = next((i for i, h in enumerate(header) if _NAME_HEADER.search(h) and i != id_col), 0)
        records = [
            SponsorRecord(country="FI", source="fi", evidence="licence", legal_name=r[name_col],
                          registry_id=r[id_col] or None, route="Certified employer")
            for r in rows[1:] if len(r) > max(id_col, name_col) and r[name_col]
        ]
        digest = hashlib.sha256("\n".join(f"{r.legal_name}|{r.registry_id}" for r in records).encode()).hexdigest()
        return digest[:16], records
    raise RegisterFormatError("FI register: no table with a Business ID column")


class FiRegister:
    """Migri certified employers. Behind a Cloudflare challenge as of 2026-10-13 → reported as blocked."""

    name = "fi"

    def __init__(self) -> None:
        self._cache: tuple[str, list[SponsorRecord]] | None = None

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        if is_bot_challenge(resp):
            raise RegisterBlocked(f"migri.fi serves a bot challenge (HTTP {resp.status_code}); not bypassed")
        resp.raise_for_status()
        self._cache = parse_page(resp.text)
        return self._cache[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        if self._cache is None or self._cache[0] != version:
            await self.latest(http)
        return self._cache[1]
