from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, ProbeResult
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

BASE = "https://apply.workable.com/api/v1/widget/accounts"


class Workable:
    """Workable widget API (undocumented, behind Cloudflare; covered by the smoke workflow)."""

    name = "workable"
    provides_name = True

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        resp = await http.get(f"{BASE}/{slug}", params={"details": "true"})
        if resp.status_code == 404:
            raise BoardNotFound(f"workable:{slug}")
        resp.raise_for_status()
        postings = []
        for job in resp.json().get("jobs", []):
            visible = [loc for loc in job.get("locations") or [] if not loc.get("hidden")]
            first = visible[0] if visible else {}
            parts = (job.get("city") or first.get("city"), job.get("state") or first.get("region"),
                     job.get("country") or first.get("country"))
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["shortcode"]), title=(job.get("title") or "").strip(),
                url=job.get("url") or job.get("shortlink") or "", description=html_to_text(job.get("description")),
                location_raw=", ".join(p for p in parts if p) or None,
                country=country_code(first.get("countryCode")) or country_code(job.get("country")),
                remote="remote" if job.get("telecommuting") else None,
                posted_at=job.get("published_on") or job.get("created_at") or None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True, resp.json().get("name"))
