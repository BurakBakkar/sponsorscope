from __future__ import annotations

import json
import re
from urllib.parse import quote

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, DetailBudget, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

DETAIL_BUDGET = 10_000  # new-posting detail calls per run (one shared host), so a big first crawl spans nights
API = "https://api.rippling.com/platform/api/ats/v1/board"
BOARD = "https://ats.rippling.com"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)
_PAREN = re.compile(r"\(([^()]+)\)\s*$")


def _country(location: str) -> str | None:
    """'Remote (United States)' / 'Warszawa, Poland' → ISO-2; 'New York, NY' stays None (CA is not Canada)."""
    match = _PAREN.search(location)
    tail = (match[1] if match else location.rsplit(",", 1)[-1]).strip()
    return country_code(tail) if len(tail) > 2 else None


class Rippling:
    """Rippling ATS public board API: one unpaginated list call, then a detail call per posting.

    The list repeats a posting once per work location. The company name is only on the detail
    resource and on the public board page, which embeds it even for boards with no openings.
    """

    name = "rippling"
    provides_name = True

    def __init__(self, detail_budget: int = DETAIL_BUDGET) -> None:
        self._budget = DetailBudget(detail_budget)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"rippling:{slug}")
        api = f"{API}/{quote(slug, safe='')}/jobs"
        resp = await http.get(api)
        if resp.status_code == 404:
            raise BoardNotFound(f"rippling:{slug}")
        resp.raise_for_status()
        jobs: dict[str, dict] = {}
        for it in resp.json() or []:
            if not isinstance(it, dict) or not it.get("uuid"):
                continue
            job = jobs.setdefault(it["uuid"], {**it, "locations": []})
            label = (it.get("workLocation") or {}).get("label")
            if label and label not in job["locations"]:
                job["locations"].append(label)
        postings = []
        for uuid, job in jobs.items():
            skip = f"{self.name}:{slug}:{uuid}" in known_ids or not self._budget.take()
            info = {} if skip else await self._detail(http, api, uuid)
            locations = [loc for loc in info.get("workLocations") or [] if loc] or job["locations"]
            countries = {_country(loc) for loc in locations}
            desc = info.get("description") or {}
            created = info.get("createdOn")
            url = job.get("url") or ""
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=uuid, title=(job.get("name") or info.get("name") or "").strip(),
                url=url if url.startswith(f"{BOARD}/") else f"{BOARD}/{quote(slug, safe='')}/jobs/{quote(uuid, safe='')}",
                description=None if skip else "\n".join(
                    t for t in (html_to_text(desc.get("company")), html_to_text(desc.get("role"))) if t),
                location_raw="; ".join(locations) or None,
                country=countries.pop() if len(countries) == 1 else None,
                remote=infer_remote(" ".join(locations)), posted_at=created[:10] if created else None,
            ))
        return postings

    async def _detail(self, http: Http, api: str, uuid: str) -> dict:
        resp = await http.get(f"{api}/{quote(uuid, safe='')}")
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        resp = await http.get(f"{BOARD}/{quote(slug, safe='')}/jobs")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        match = _NEXT_DATA.search(resp.text)
        try:
            name = json.loads(match[1])["props"]["pageProps"]["apiData"]["jobBoard"]["companyName"]
        except (ValueError, KeyError, TypeError):
            name = None
        return ProbeResult(True, name.strip() or None if isinstance(name, str) else None)
