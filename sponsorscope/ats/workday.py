from __future__ import annotations

import re
import urllib.robotparser

from sponsorscope.ats.base import BoardNotFound, DetailBudget, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import USER_AGENT, Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

PAGE_SIZE = 20  # the CXS API's maximum
DETAIL_BUDGET = 25_000  # new-posting detail calls per run; ~4k tenants hold ~650k postings, so the backlog takes weeks
_HOST = re.compile(r"(?P<tenant>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", re.I)


def _split(slug: str) -> tuple[str, str, str]:
    host, _, site = slug.partition("/")
    match = _HOST.fullmatch(host)
    if not match or not site or "/" in site:
        raise BoardNotFound(f"workday:{slug} (expected <tenant>.wdN.myworkdayjobs.com/<site>)")
    return host, match["tenant"], site


class Workday:
    """Workday career sites through the CXS JSON API the public career page itself calls.

    The slug is "<tenant>.wdN.myworkdayjobs.com/<site>" (e.g. embl.wd103.myworkdayjobs.com/embl); seeded by hand.
    Tenants list their public site paths in robots.txt; a site whose path is disallowed is never fetched.
    """

    name = "workday"
    provides_name = False

    def __init__(self, detail_budget: int = DETAIL_BUDGET) -> None:
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._budget = DetailBudget(detail_budget)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        host, tenant, site = _split(slug)
        if not await self._allowed(http, host, site):
            raise BoardNotFound(f"workday:{slug} (robots.txt disallows this site)")
        api = f"https://{host}/wday/cxs/{tenant}/{site}"
        postings = []
        for it in await self._list(http, api, slug):
            path = it.get("externalPath") or ""
            req_id = (it.get("bulletFields") or [None])[0] or path.rsplit("_", 1)[-1]
            detail = f"{self.name}:{slug}:{req_id}" not in known_ids and self._budget.take()
            info = await self._detail(http, api, path) if detail else {}
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=req_id, title=(it.get("title") or "").strip(),
                url=info.get("externalUrl") or f"https://{host}/{site}{path}",
                description=html_to_text(info.get("jobDescription")) if detail else None,
                location_raw=it.get("locationsText") or info.get("location"),
                country=country_code((info.get("country") or {}).get("descriptor")),
                remote=infer_remote(info.get("remoteType")), posted_at=info.get("startDate"),
            ))
        return postings

    async def _list(self, http: Http, api: str, slug: str) -> list[dict]:
        items: list[dict] = []
        total = None
        while total is None or len(items) < total:
            resp = await http.post(f"{api}/jobs", json={
                "limit": PAGE_SIZE, "offset": len(items), "appliedFacets": {}, "searchText": ""})
            if resp.status_code in (404, 422):
                raise BoardNotFound(f"workday:{slug}")
            resp.raise_for_status()
            data = resp.json()
            if total is None:
                total = data.get("total") or 0  # only the first page carries the real total
            page = data.get("jobPostings") or []
            if not page:
                break
            items += page
        return items

    async def _detail(self, http: Http, api: str, path: str) -> dict:
        resp = await http.get(f"{api}{path}")
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json().get("jobPostingInfo") or {}

    async def _allowed(self, http: Http, host: str, site: str) -> bool:
        if host not in self._robots:
            resp = await http.get(f"https://{host}/robots.txt")
            parser = None
            if resp.status_code == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.lower().splitlines())  # rules say /EMBL/, the API takes /embl/
            self._robots[host] = parser
        parser = self._robots[host]
        return parser is None or parser.can_fetch(USER_AGENT.lower(), f"https://{host}/{site.lower()}/")

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        try:
            host, tenant, site = _split(slug)
            if not await self._allowed(http, host, site):
                return ProbeResult(False)
            first = await http.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                                    json={"limit": 1, "offset": 0, "appliedFacets": {}, "searchText": ""})
        except BoardNotFound:
            return ProbeResult(False)
        return ProbeResult(first.status_code == 200)
