from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

BASE = "https://api.ashbyhq.com/posting-api/job-board"
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}


class Ashby:
    """Ashby public posting API. `isRemote` is unreliable (true on hybrid jobs); prefer workplaceType."""

    name = "ashby"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            raise BoardNotFound(f"ashby:{slug}")
        resp.raise_for_status()
        postings = []
        for job in resp.json().get("jobs", []):
            if job.get("isListed") is False:
                continue
            address = (job.get("address") or {}).get("postalAddress") or {}
            location = job.get("location")
            workplace = (job.get("workplaceType") or "").lower().replace(" ", "")
            remote = WORKPLACE.get(workplace) or ("remote" if job.get("isRemote") else None) or infer_remote(location)
            published = job.get("publishedAt")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["id"]), title=(job.get("title") or "").strip(),
                url=job.get("jobUrl") or "",
                description=(job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml"))).strip(),
                location_raw=location, country=country_code(address.get("addressCountry")), remote=remote,
                posted_at=published[:10] if published else None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True)
