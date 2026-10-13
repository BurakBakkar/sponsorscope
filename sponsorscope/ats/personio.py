from __future__ import annotations

from defusedxml.ElementTree import fromstring

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, ProbeResult, infer_remote
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text


def _base(slug: str) -> str:
    return f"https://{slug}.jobs.personio.de"


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _is_xml(resp) -> bool:
    return "xml" in resp.headers.get("content-type", "").lower()


class Personio:
    """Personio public XML feed. Unknown slugs return an HTML 404 page; XML is parsed with defusedxml."""

    name = "personio"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"personio:{slug} (not a valid subdomain)")
        resp = await http.get(f"{_base(slug)}/xml")
        if resp.status_code == 404:
            raise BoardNotFound(f"personio:{slug}")
        resp.raise_for_status()
        if not _is_xml(resp):
            raise BoardNotFound(f"personio:{slug} (not an XML feed)")
        postings = []
        for pos in fromstring(resp.content).findall("position"):
            pid = _text(pos, "id")
            offices = [_text(pos, "office")] + [(o.text or "").strip() for o in pos.findall("additionalOffices/office")]
            location = "; ".join(o for o in offices if o) or None
            sections = []
            for d in pos.findall("jobDescriptions/jobDescription"):
                body = "\n".join(t for t in (_text(d, "name"), html_to_text(_text(d, "value"))) if t)
                if body:
                    sections.append(body)
            created = _text(pos, "createdAt")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=pid, title=_text(pos, "name"), url=f"{_base(slug)}/job/{pid}",
                description="\n".join(sections), location_raw=location, country=None,
                remote=infer_remote(location), posted_at=created[:10] or None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        resp = await http.get(f"{_base(slug)}/xml")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(_is_xml(resp))
