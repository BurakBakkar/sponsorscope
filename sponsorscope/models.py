from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SponsorRecord:
    """One entry from an official sponsor register or sponsorship-history dataset."""

    country: str  # ISO-3166 alpha-2, e.g. "GB"
    source: str  # register plugin name, e.g. "gb"
    evidence: str  # "licence" | "history"
    legal_name: str
    registry_id: str | None = None  # KVK / CVR / business ID when present
    city: str | None = None
    route: str | None = None  # e.g. "Skilled Worker", "H-1B"
    filings: int | None = None  # history sources: certified filings / permits
    period: str | None = None  # history sources: e.g. "FY2026", "2026 Q1"


@dataclass(frozen=True)
class RawPosting:
    """A job posting as returned by an ATS adapter, before enrichment."""

    ats: str
    slug: str
    job_id: str
    title: str
    url: str
    description: str | None  # plain text; None = known posting not re-fetched (keep stored label)
    location_raw: str | None
    country: str | None  # ISO-2 from structured ATS fields, if the ATS provides one
    remote: str | None  # "remote" | "hybrid" | "onsite" | None
    posted_at: str | None  # ISO date "YYYY-MM-DD"

    @property
    def id(self) -> str:
        return f"{self.ats}:{self.slug}:{self.job_id}"


@dataclass(frozen=True)
class Label:
    sponsorship: str  # "yes" | "no" | "unknown"
    mixed: bool  # True when yes- and no-rules both matched
    languages_required: tuple[str, ...]  # ISO-639-1 codes
    evidence: tuple[str, ...]  # matched phrases with context


def content_hash(text: str) -> str:
    normalised = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
