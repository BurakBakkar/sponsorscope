from __future__ import annotations

import re
import urllib.robotparser
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser, LexborNode

from sponsorscope.ats.base import BoardNotFound, DetailBudget, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import USER_AGENT, Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

DETAIL_BUDGET = 10_000  # new-posting detail pages per run, across all sites
MAX_PAGES = 100  # 25-100 rows a page; no seeded site comes close
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_JOB_ID = re.compile(r"^(?:/[^/?#]+)?/job/[^?#]*/(\d+)/?$")  # brand sites prefix the path: /Kerecis/job/...
_TOTAL = re.compile(r"\bof\s+([\d.,\s]+?)\s*(?:jobs\b|$)", re.I)  # "Results 1 – 100 of 143", "Showing 1 to 23 of 23 Jobs"


def _search_url(host: str, start: int) -> str:
    return f"https://{host}/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow={start}"


def _text(node: LexborNode | None) -> str | None:
    return " ".join(node.text().split()) or None if node else None


def _total(tree: LexborHTMLParser) -> int | None:
    for node in tree.css(".paginationLabel, #tile-search-results-label"):
        if match := _TOTAL.search(" ".join(node.text().split())):
            return int(re.sub(r"\D", "", match[1]))
    return None


def parse_search(page: str) -> tuple[list[tuple[str, str, str, str | None]], int | None]:
    """((job id, path, title, location) per row, total) from a search page in the table or the tile layout."""
    tree = LexborHTMLParser(page)
    rows = []
    for row in tree.css("tr.data-row, li.job-tile"):
        link = row.css_first("a.jobTitle-link")
        path = (link.attributes.get("href") or "") if link else ""
        if not (match := _JOB_ID.match(path)):
            continue
        location = row.css_first("span.jobLocation, [id$='-section-location-value']")
        rows.append((match[1], path, _text(link) or "", _text(location)))
    return rows, _total(tree)


def _location_country(location: str | None) -> str | None:
    """"City, [State,] CC, postcode": the last two-letter part ("Cambridge, MA, US, MA 02139": MA is the state);
    else a trailing country name ("Switzerland")."""
    parts = [part.strip() for part in (location or "").split(",")]
    codes = [part for part in parts if re.fullmatch(r"[A-Z]{2}", part)]
    if codes:
        return country_code(codes[-1])
    return country_code(parts[-1]) if len(parts[-1]) > 3 else None


def _date(value: str | None) -> str | None:
    try:  # "Sun Oct 25 02:00:00 UTC 2026"
        return datetime.strptime(value or "", "%a %b %d %H:%M:%S %Z %Y").date().isoformat()
    except ValueError:
        return None


def parse_job(page: str) -> dict:
    """schema.org microdata on the job page: description html, country, date posted."""
    tree = LexborHTMLParser(page)

    def content(prop: str) -> str | None:
        node = tree.css_first(f'[itemprop="{prop}"][content]')
        return node.attributes.get("content") if node else None

    description = tree.css_first('[itemprop="description"]')
    place = [content(p) for p in ("addressLocality", "addressRegion", "addressCountry")]
    location = _text(tree.css_first(".jobGeoLocation")) or content("streetAddress") or ", ".join(filter(None, place))
    return {"description": description.html if description else None, "location": location or None,
            "country": content("addressCountry"), "posted_at": _date(content("datePosted"))}


class SuccessFactors:
    """SAP SuccessFactors Recruiting Marketing career sites (jobs.<company>.com, "j2w" pages), crawled through
    the /search/ pages and job pages that robots.txt leaves open (it disallows the /services/ RSS feed).

    The slug is the site's host, e.g. jobs.biontech.com; seeded by hand.
    """

    name = "successfactors"
    provides_name = False

    def __init__(self, detail_budget: int = DETAIL_BUDGET) -> None:
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._budget = DetailBudget(detail_budget)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not _HOST.fullmatch(slug):
            raise BoardNotFound(f"successfactors:{slug} (expected the career site's host name)")
        if not await self._allowed(http, slug, "/search/"):
            raise BoardNotFound(f"successfactors:{slug} (robots.txt disallows /search/)")
        postings = []
        for job_id, path, title, location in await self._list(http, slug):
            detail = f"{self.name}:{slug}:{job_id}" not in known_ids and self._budget.take()
            info = await self._detail(http, slug, path) if detail else {}
            location = location or info.get("location")  # some tile layouts list no location
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=job_id, title=title, url=f"https://{slug}{path}",
                description=html_to_text(info.get("description")) if detail else None,
                location_raw=location, country=country_code(info.get("country")) or _location_country(location),
                remote=infer_remote(location), posted_at=info.get("posted_at"),
            ))
        return postings

    async def _list(self, http: Http, host: str) -> list[tuple[str, str, str, str | None]]:
        rows: dict[str, tuple[str, str, str, str | None]] = {}
        start = 0
        for _ in range(MAX_PAGES):
            resp = await http.get(_search_url(host, start))
            if resp.status_code == 404:
                raise BoardNotFound(f"successfactors:{host}")
            resp.raise_for_status()
            page, total = parse_search(resp.text)
            new = [r for r in page if r[0] not in rows]
            if not new:
                break
            rows.update((r[0], r) for r in new)
            start += len(page)
            if total is not None and start >= total:
                break
        return list(rows.values())

    async def _detail(self, http: Http, host: str, path: str) -> dict:
        if not await self._allowed(http, host, path):
            return {}
        resp = await http.get(f"https://{host}{path}", follow_redirects=False)
        if resp.status_code == 404 or resp.is_redirect:  # filled jobs redirect to the search page
            return {}
        resp.raise_for_status()
        return parse_job(resp.text)

    async def _allowed(self, http: Http, host: str, path: str) -> bool:
        if host not in self._robots:
            resp = await http.get(f"https://{host}/robots.txt")
            parser = None
            if resp.status_code == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
            self._robots[host] = parser
        parser = self._robots[host]
        return parser is None or parser.can_fetch(USER_AGENT, f"https://{host}{path}")

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not _HOST.fullmatch(slug) or not await self._allowed(http, slug, "/search/"):
            return ProbeResult(False)
        resp = await http.get(_search_url(slug, 0))
        return ProbeResult(resp.status_code == 200 and "jobTitle-link" in resp.text)
