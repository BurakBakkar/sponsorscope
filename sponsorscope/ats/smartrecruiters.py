from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, DetailBudget, ProbeResult
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

API = "https://api.smartrecruiters.com/v1/companies"
CAREERS = "https://careers.smartrecruiters.com"
JOBS = "https://jobs.smartrecruiters.com"
PAGE_SIZE = 100
SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
DETAIL_BUDGET = 20_000  # new-posting detail calls per run (one API host); a big first crawl spans nights


def _dedupe_languages(items: list[dict]) -> list[dict]:
    """The same job is published once per language; keep one per refNumber, English preferred."""
    chosen: dict[str, dict] = {}
    for it in items:
        key = it.get("refNumber") or it["id"]
        is_en = ((it.get("language") or {}).get("code") or "").lower().startswith("en")
        if key not in chosen or (is_en and not chosen[key]["_en"]):
            chosen[key] = {**it, "_en": is_en}
    return list(chosen.values())


class SmartRecruiters:
    """Public Posting API. Unknown companies return 200 + empty list, so existence is checked separately."""

    name = "smartrecruiters"
    provides_name = False

    def __init__(self, detail_budget: int = DETAIL_BUDGET) -> None:
        self._budget = DetailBudget(detail_budget)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        listing = await self._list(http, slug)
        if not listing and not (await self.probe(http, slug)).exists:
            raise BoardNotFound(f"smartrecruiters:{slug}")
        postings = []
        for it in _dedupe_languages(listing):
            pid = str(it["id"])
            new = f"{self.name}:{slug}:{pid}" not in known_ids and self._budget.take()
            loc = it.get("location") or {}
            released = it.get("releasedDate")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=pid, title=(it.get("name") or "").strip(),
                url=f"{JOBS}/{slug}/{pid}",
                description=await self._description(http, slug, pid) if new else None,
                location_raw=loc.get("fullLocation"), country=country_code(loc.get("country")),
                remote="remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else None,
                posted_at=released[:10] if released else None,
            ))
        return postings

    async def _list(self, http: Http, slug: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            resp = await http.get(f"{API}/{slug}/postings", params={"limit": PAGE_SIZE, "offset": offset})
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content") or []
            items += content
            offset += PAGE_SIZE
            if not content or offset >= (data.get("totalFound") or 0):
                return items

    async def _description(self, http: Http, slug: str, pid: str) -> str:
        resp = await http.get(f"{API}/{slug}/postings/{pid}")
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        sections = ((resp.json().get("jobAd") or {}).get("sections")) or {}
        texts = [html_to_text((sections.get(key) or {}).get("text")) for key in SECTIONS]
        return "\n".join(t for t in texts if t)

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{CAREERS}/{slug}", follow_redirects=False)
        if resp.status_code == 200:
            return ProbeResult(True)
        if resp.is_redirect or resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(False)
