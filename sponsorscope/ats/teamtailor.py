from __future__ import annotations

from email.utils import parsedate_to_datetime

from defusedxml.ElementTree import fromstring

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

TT = "{https://teamtailor.com/locations}"
_REMOTE = {"fully": "remote", "remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def _url(slug: str) -> str:
    return f"https://{slug}.teamtailor.com/jobs.rss"


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _is_xml(resp) -> bool:
    return "xml" in resp.headers.get("content-type", "").lower()


def _date(value: str) -> str | None:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


class Teamtailor:
    """Teamtailor career-site RSS. Unknown slugs return an HTML 404; channel <title> is often
    "<Company> Careers"-style, so no company name is reported."""

    name = "teamtailor"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"teamtailor:{slug} (not a valid subdomain)")
        resp = await http.get(_url(slug))
        if resp.status_code == 404:
            raise BoardNotFound(f"teamtailor:{slug}")
        resp.raise_for_status()
        if not _is_xml(resp):
            raise BoardNotFound(f"teamtailor:{slug} (not an RSS feed)")
        postings = []
        for item in fromstring(resp.content).findall("channel/item"):
            places, countries = [], set()
            for loc in item.findall(f"{TT}locations/{TT}location"):
                city, country = _text(loc, f"{TT}city") or _text(loc, f"{TT}name"), _text(loc, f"{TT}country")
                places.append(", ".join(p for p in (city, country) if p))
                countries.add(country_code(country))
            location = "; ".join(p for p in places if p) or None
            status = _text(item, "remoteStatus").lower()
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=_text(item, "guid"), title=_text(item, "title"),
                url=_text(item, "link"), description=html_to_text(_text(item, "description")),
                location_raw=location, country=countries.pop() if len(countries) == 1 else None,
                remote=_REMOTE.get(status) or infer_remote(location), posted_at=_date(_text(item, "pubDate")),
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        resp = await http.get(_url(slug))
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(_is_xml(resp))
