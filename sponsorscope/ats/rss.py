from __future__ import annotations

import email.utils
import hashlib
import html
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from defusedxml.ElementTree import fromstring

from sponsorscope.ats.base import BoardNotFound, ProbeResult
from sponsorscope.classify.level import detect_level
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

_TLD_COUNTRY = {"uk": "GB"}  # ccTLDs that differ from the ISO code
_RSS1 = "{http://purl.org/rss/1.0/}"
_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"
_HOST = re.compile(r"[a-z0-9.-]+(?::\d+)?", re.I)
_ID_PARAMS = ("ref", "show")  # query parameters that carry a stable vacancy id


def _text(node, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _date(value: str) -> str | None:
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _feed_url(slug: str) -> str:
    return f"https://{slug.split('#', 1)[0]}"


def _fix_link(link: str, feed_url: str) -> str:
    """Some CMSes emit item links with a garbage host (cms.ku.dkObvius::Document=HASH(…)?show=1): keep the query,
    resolve it against the feed's own address."""
    parts = urlsplit(link)
    if parts.scheme not in ("http", "https") or _HOST.fullmatch(parts.netloc):
        return link
    feed = urlsplit(feed_url)
    return urlunsplit((feed.scheme, feed.netloc, feed.path, parts.query, ""))


def _job_id(link: str, guid: str) -> str:
    if guid and not guid.startswith(("http://", "https://")):
        return guid
    query = parse_qs(urlsplit(guid or link).query)
    for param in _ID_PARAMS:
        if query.get(param):
            return query[param][0]
    return hashlib.sha256((guid or link).encode()).hexdigest()[:16]


def _description(markup: str) -> str:
    if "<" not in markup and "&lt;" in markup:  # SuccessFactors escapes its HTML inside CDATA
        markup = html.unescape(markup)
    return html_to_text(markup)


class UniversityRss:
    """University vacancy RSS 2.0 / RSS 1.0 feeds; keeps only PhD and master's offers.

    The slug is the feed URL without its scheme (e.g. jobs.nottingham.ac.uk/rss/rss.aspx), so boards are
    seeded by hand and never slug-guessed. Feeds carry no location: the country comes from the ccTLD, or from
    a `#country=SE` fragment on the slug for generic hosts like varbi.com (fragments are never sent).
    """

    name = "rss"
    provides_name = False

    @staticmethod
    def country_for(slug: str) -> str | None:
        fragment = parse_qs(slug.split("#", 1)[1]) if "#" in slug else {}
        if fragment.get("country"):
            return country_code(fragment["country"][0])
        tld = (urlsplit(_feed_url(slug)).hostname or "").rsplit(".", 1)[-1]
        return _TLD_COUNTRY.get(tld) or (country_code(tld) if len(tld) == 2 else None)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        url = _feed_url(slug)
        resp = await http.get(url)
        if resp.status_code == 404:
            raise BoardNotFound(f"rss:{slug}")
        resp.raise_for_status()
        root = fromstring(resp.content)
        channel = root.find("channel")
        if channel is not None:
            items, ns, date_tag = channel.findall("item"), "", "pubDate"
        elif root.find(f"{_RSS1}channel") is not None:
            items, ns, date_tag = root.findall(f"{_RSS1}item"), _RSS1, _DC_DATE
        else:
            raise BoardNotFound(f"rss:{slug} (not an RSS feed)")
        country = self.country_for(slug)
        postings = []
        for item in items:
            title = html.unescape(html.unescape(_text(item, f"{ns}title")))  # some feeds double-escape (&amp;amp;)
            level = detect_level(title, html.unescape(_text(item, f"{ns}category")))
            if level is None:
                continue
            link, guid = _fix_link(_text(item, f"{ns}link"), url), _fix_link(_text(item, f"{ns}guid"), url)
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=_job_id(link, guid), title=title, url=link or guid,
                description=_description(_text(item, f"{ns}description")), location_raw=None, country=country,
                remote=None, posted_at=_date(_text(item, date_tag)), level=level,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(_feed_url(slug))
        return ProbeResult(resp.status_code == 200 and b"<rss" in resp.content[:4096])
