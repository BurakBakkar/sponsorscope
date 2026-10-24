from __future__ import annotations

import email.utils
import hashlib
import html
from urllib.parse import parse_qs, urlsplit

from defusedxml.ElementTree import fromstring

from sponsorscope.ats.base import BoardNotFound, ProbeResult
from sponsorscope.classify.level import detect_level
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

_TLD_COUNTRY = {"uk": "GB"}  # ccTLDs that differ from the ISO code


def _text(node, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _date(value: str) -> str | None:
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _job_id(link: str, guid: str) -> str:
    ref = parse_qs(urlsplit(guid or link).query).get("ref")
    return ref[0] if ref else hashlib.sha256((guid or link).encode()).hexdigest()[:16]


class UniversityRss:
    """University vacancy RSS 2.0 feeds; keeps only PhD and master's offers.

    The slug is the feed URL without its scheme (e.g. jobs.nottingham.ac.uk/rss/rss.aspx), so boards are
    seeded by hand and never slug-guessed. Feeds carry no location: the country comes from the ccTLD.
    """

    name = "rss"
    provides_name = False

    @staticmethod
    def country_for(slug: str) -> str | None:
        tld = (urlsplit(f"https://{slug}").hostname or "").rsplit(".", 1)[-1]
        return _TLD_COUNTRY.get(tld) or (country_code(tld) if len(tld) == 2 else None)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        resp = await http.get(f"https://{slug}")
        if resp.status_code == 404:
            raise BoardNotFound(f"rss:{slug}")
        resp.raise_for_status()
        channel = fromstring(resp.content).find("channel")
        if channel is None:
            raise BoardNotFound(f"rss:{slug} (not an RSS feed)")
        country = self.country_for(slug)
        postings = []
        for item in channel.findall("item"):
            title = html.unescape(html.unescape(_text(item, "title")))  # some feeds double-escape (&amp;amp;)
            level = detect_level(title, html.unescape(_text(item, "category")))
            if level is None:
                continue
            link, guid = _text(item, "link"), _text(item, "guid")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=_job_id(link, guid), title=title, url=link or guid,
                description=html_to_text(_text(item, "description")), location_raw=None, country=country,
                remote=None, posted_at=_date(_text(item, "pubDate")), level=level,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"https://{slug}")
        return ProbeResult(resp.status_code == 200 and b"<rss" in resp.content[:4096])
