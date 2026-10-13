from __future__ import annotations

import html

from sponsorscope.ats.base import BoardNotFound, infer_remote
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

BASE = "https://boards-api.greenhouse.io/v1/boards"


class Greenhouse:
    name = "greenhouse"

    async def fetch(self, http: Http, slug: str) -> list[RawPosting]:
        resp = await http.get(f"{BASE}/{slug}/jobs", params={"content": "true"})
        if resp.status_code == 404:
            raise BoardNotFound(f"greenhouse:{slug}")
        resp.raise_for_status()
        seen: set[object] = set()
        postings = []
        for job in resp.json().get("jobs", []):
            key = job.get("internal_job_id") or job["id"]  # one job can have several postings
            if key in seen:
                continue
            seen.add(key)
            location = (job.get("location") or {}).get("name")
            published = job.get("first_published") or job.get("updated_at")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["id"]),
                title=(job.get("title") or "").strip(), url=job.get("absolute_url") or "",
                description=html_to_text(html.unescape(job.get("content") or "")),
                location_raw=location, country=None, remote=infer_remote(location),
                posted_at=published[:10] if published else None,
            ))
        return postings
