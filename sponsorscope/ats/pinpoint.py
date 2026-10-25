from __future__ import annotations

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

SECTIONS = ("description", "key_responsibilities", "skills_knowledge_expertise", "benefits")
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on_site": "onsite", "office": "onsite"}


def _url(slug: str) -> str:
    return f"https://{slug}.pinpointhq.com/jobs.json"


async def _get(http: Http, slug: str):
    resp = await http.get(_url(slug))
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    if "json" not in resp.headers.get("content-type", ""):  # renamed boards 301 elsewhere; never parse an HTML page
        return None
    return resp


class Pinpoint:
    """Pinpoint careers-site feed. No company name or posting date in the payload; location has no country field."""

    name = "pinpoint"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"pinpoint:{slug} (not a valid subdomain)")
        resp = await _get(http, slug)
        if resp is None:
            raise BoardNotFound(f"pinpoint:{slug}")
        postings = []
        for job in resp.json().get("data", []):
            location = (job.get("location") or {}).get("name")
            remote = WORKPLACE.get((job.get("workplace_type") or "").lower()) or infer_remote(location)
            text = [html_to_text(job.get(k)) for k in SECTIONS]
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["id"]), title=(job.get("title") or "").strip(),
                url=job.get("url") or f"https://{slug}.pinpointhq.com{job.get('path') or ''}",
                description="\n".join(t for t in text if t), location_raw=location,
                country=country_code(location) if location and len(location) > 3 else None,  # "CA"/"IN" may be states
                remote=remote, posted_at=None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        return ProbeResult(await _get(http, slug) is not None)
