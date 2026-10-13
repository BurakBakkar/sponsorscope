from __future__ import annotations

from typing import Protocol

import httpx

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord


class RegisterFormatError(Exception):
    """The upstream file or page no longer looks like what the parser expects."""


class Register(Protocol):
    name: str  # ISO-2 lowercase, also the `source` column value

    async def latest(self, http: Http) -> str:
        """Cheap version signal (URL, date, etc.). Unchanged version → skip fetch."""
        ...

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]: ...


class RegisterBlocked(Exception):
    """The source refuses automated access (bot challenge). Reported as 'blocked'; never bypassed."""


def is_bot_challenge(resp: httpx.Response) -> bool:
    if resp.status_code not in (403, 429, 503):
        return False
    return "cf-mitigated" in resp.headers or "just a moment" in resp.text[:4000].lower()
