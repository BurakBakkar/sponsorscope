from __future__ import annotations

from datetime import datetime, timezone

from sponsorscope.ats.base import BoardNotFound, ProbeResult, infer_remote
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

HOSTS = ("https://api.lever.co", "https://api.eu.lever.co")
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}


class Lever:
    """Lever postings API. Slugs are case-sensitive; EU accounts live on a separate host."""

    name = "lever"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        for host in HOSTS:
            resp = await http.get(f"{host}/v0/postings/{slug}", params={"mode": "json"})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return [self._parse(slug, p) for p in resp.json()]
        raise BoardNotFound(f"lever:{slug}")

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        for host in HOSTS:
            resp = await http.get(f"{host}/v0/postings/{slug}", params={"mode": "json", "limit": 1})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return ProbeResult(True)
        return ProbeResult(False)

    def _parse(self, slug: str, p: dict) -> RawPosting:
        location = (p.get("categories") or {}).get("location")
        parts = [p.get("descriptionPlain") or ""]
        for section in p.get("lists") or []:
            parts += [section.get("text") or "", html_to_text(section.get("content"))]
        parts.append(p.get("additionalPlain") or "")
        created = p.get("createdAt")
        country = p.get("country")
        return RawPosting(
            ats=self.name, slug=slug, job_id=str(p["id"]),
            title=(p.get("text") or "").strip(), url=p.get("hostedUrl") or "",
            description="\n".join(part for part in parts if part).strip(),
            location_raw=location, country=country.upper() if country else None,
            remote=WORKPLACE.get((p.get("workplaceType") or "").lower()) or infer_remote(location),
            posted_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat() if created else None,
        )
