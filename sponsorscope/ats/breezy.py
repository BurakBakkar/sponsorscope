from __future__ import annotations

import json

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, DetailBudget, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

DETAIL_BUDGET = 10_000  # new-posting detail calls per run (one shared host), so a big first crawl spans nights


def _base(slug: str) -> str:
    return f"https://{slug}.breezy.hr"


def _description_html(page: str) -> str | None:
    """schema.org JobPosting JSON-LD; pages without it (e.g. fully remote roles) still render div.description."""
    tree = LexborHTMLParser(page)
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting" and data.get("description"):
            return data["description"]
    node = tree.css_first("div.description")
    return node.html if node else None


class Breezy:
    """Breezy HR public /json feed (no descriptions); each position page supplies those.

    Unknown boards answer 404 with an HTML "Career portal not found" page.
    """

    name = "breezy"
    provides_name = False  # company name only rides along on positions, so empty boards have none

    def __init__(self, detail_budget: int = DETAIL_BUDGET) -> None:
        self._budget = DetailBudget(detail_budget)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        positions = await self._list(http, slug)
        if positions is None:
            raise BoardNotFound(f"breezy:{slug}")
        postings = []
        for p in positions:
            pid = str(p.get("id") or p.get("_id") or "")
            if not pid:
                continue
            new = f"{self.name}:{slug}:{pid}" not in known_ids and self._budget.take()
            loc = p.get("location") if isinstance(p.get("location"), dict) else {}
            remote = infer_remote((loc.get("remote_details") or {}).get("value")) or (
                "remote" if loc.get("is_remote") or p.get("is_remote") else None)
            published = p.get("published_date")
            url = p.get("url") or f"{_base(slug)}/p/{p.get('friendly_id') or pid}"
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=pid, title=(p.get("name") or "").strip(), url=url,
                description=await self._description(http, url) if new else None,
                location_raw=loc.get("name"), country=country_code((loc.get("country") or {}).get("id")),
                remote=remote, posted_at=published[:10] if published else None,
            ))
        return postings

    async def _list(self, http: Http, slug: str) -> list[dict] | None:
        """Positions, or None when the board doesn't exist."""
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return None
        resp = await http.get(f"{_base(slug)}/json", follow_redirects=False)
        if resp.status_code == 404 or resp.is_redirect:
            return None
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            return None
        if isinstance(data, dict):
            data = data.get("positions")
        return data if isinstance(data, list) else None

    async def _description(self, http: Http, url: str) -> str:
        resp = await http.get(url, follow_redirects=False)
        if resp.status_code == 404 or resp.is_redirect:  # closed positions redirect to the board
            return ""
        resp.raise_for_status()
        return html_to_text(_description_html(resp.text))

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        return ProbeResult(await self._list(http, slug) is not None)
