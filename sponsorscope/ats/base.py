from __future__ import annotations

from typing import Protocol

from sponsorscope.http import Http
from sponsorscope.models import RawPosting


class BoardNotFound(Exception):
    """The ATS says this board/slug does not exist."""


class ATS(Protocol):
    name: str

    async def fetch(self, http: Http, slug: str) -> list[RawPosting]:
        """All current postings on a board. Raises BoardNotFound if the board doesn't exist."""
        ...


def infer_remote(text: str | None) -> str | None:
    low = (text or "").lower()
    if "hybrid" in low:
        return "hybrid"
    if "remote" in low:
        return "remote"
    return None
