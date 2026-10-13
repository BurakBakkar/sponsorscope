from __future__ import annotations

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, ProbeResult
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text


def _url(slug: str) -> str:
    return f"https://{slug}.recruitee.com/api/offers/"


class Recruitee:
    """Recruitee careers-site API. NOTE: requires X-Careers-Sites-Token from 2027-02-10 (spec §8)."""

    name = "recruitee"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"recruitee:{slug} (not a valid subdomain)")
        resp = await http.get(_url(slug))
        if resp.status_code == 404:
            raise BoardNotFound(f"recruitee:{slug}")
        resp.raise_for_status()
        postings = []
        for o in resp.json().get("offers", []):
            if o.get("status") not in (None, "published"):
                continue
            remote = "hybrid" if o.get("hybrid") else "remote" if o.get("remote") else "onsite" if o.get("on_site") else None
            published = o.get("published_at") or o.get("created_at")
            text = [html_to_text(o.get("description")), html_to_text(o.get("requirements"))]
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(o["id"]), title=(o.get("title") or "").strip(),
                url=o.get("careers_url") or "", description="\n".join(t for t in text if t),
                location_raw=o.get("location"), country=country_code(o.get("country_code")), remote=remote,
                posted_at=published[:10] if published else None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        resp = await http.get(_url(slug))
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True)
