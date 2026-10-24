from __future__ import annotations

from urllib.parse import parse_qsl

from sponsorscope.ats.base import BoardNotFound, ProbeResult, infer_remote
from sponsorscope.classify.level import detect_level
from sponsorscope.http import Http
from sponsorscope.models import RawPosting

SEARCH = "https://jobsearch.api.jobtechdev.se/search"
DOCTORAL = "NNK9_F1o_pK5"  # JobTech taxonomy occupation group "Doktorander"
PAGE_SIZE = 100
MAX_OFFSET = 2000  # the API refuses deeper pages


class JobTech:
    """Arbetsförmedlingen JobSearch API (Sweden's public employment service; ads are CC0, no key needed).

    Keeps only degree offers (Sweden has no sponsor register, so ordinary jobs would only be noise).
    An aggregator: each ad carries its own employer. The slug is one or more search queries joined by "|",
    e.g. "occupation-group=NNK9_F1o_pK5|q=thesis"; hits are merged by ad id so overlapping queries don't
    duplicate postings. Seeded by hand.
    """

    name = "jobtech"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        queries = [dict(parse_qsl(q)) for q in slug.split("|") if q]
        if not queries or not all(queries):
            raise BoardNotFound(f"jobtech:{slug} (expected search queries joined by '|')")
        hits: dict[str, dict] = {}
        for query in queries:
            for h in await self._search(http, query):
                hits.setdefault(str(h["id"]), h)
        postings = [self._posting(slug, ad_id, h) for ad_id, h in hits.items()]
        return [p for p in postings if p.level]

    async def _search(self, http: Http, query: dict[str, str]) -> list[dict]:
        hits: list[dict] = []
        while len(hits) < MAX_OFFSET:
            resp = await http.get(SEARCH, params={**query, "limit": PAGE_SIZE, "offset": len(hits)},
                                  headers={"accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
            page = data.get("hits") or []
            hits += page
            if not page or len(hits) >= ((data.get("total") or {}).get("value") or 0):
                break
        return hits

    def _posting(self, slug: str, ad_id: str, h: dict) -> RawPosting:
        address = h.get("workplace_address") or {}
        group = (h.get("occupation_group") or {}).get("concept_id")
        published = h.get("publication_date")
        return RawPosting(
            ats=self.name, slug=slug, job_id=ad_id, title=(h.get("headline") or "").strip(),
            url=h.get("webpage_url") or f"https://arbetsformedlingen.se/platsbanken/annonser/{ad_id}",
            description=(h.get("description") or {}).get("text") or "",
            location_raw=", ".join(p for p in (address.get("municipality"), address.get("region")) if p) or None,
            country="SE", remote=infer_remote((h.get("workplace_model") or {}).get("label")),
            posted_at=published[:10] if published else None,
            level="phd" if group == DOCTORAL else detect_level(h.get("headline") or ""),
            employer=(h.get("employer") or {}).get("name"),
        )

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        return ProbeResult(bool(slug))
