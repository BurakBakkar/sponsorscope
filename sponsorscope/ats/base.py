from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sponsorscope.http import Http
from sponsorscope.models import RawPosting

SUBDOMAIN_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class BoardNotFound(Exception):
    """The ATS says this board/slug does not exist."""


@dataclass(frozen=True)
class ProbeResult:
    exists: bool
    name: str | None = None  # company name, for ATSes that expose one


class ATS(Protocol):
    name: str
    provides_name: bool  # probe() returns the company name → guessed hits can be verified

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        """All current postings on a board. Raises BoardNotFound if the board doesn't exist.

        known_ids: posting ids already stored for this board; adapters with expensive
        per-posting detail calls may return description=None for these.
        """
        ...

    async def probe(self, http: Http, slug: str) -> ProbeResult: ...


def infer_remote(text: str | None) -> str | None:
    low = (text or "").lower()
    if "hybrid" in low:
        return "hybrid"
    if "remote" in low:
        return "remote"
    return None
