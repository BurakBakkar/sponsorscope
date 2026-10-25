from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, DetailBudget, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

API = "/hcmRestApi/resources/latest"
PAGE_SIZE = 100
SECTIONS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
DETAIL_BUDGET = 10_000  # new-posting detail calls per run, so a big first crawl spans nights


def _split(slug: str) -> tuple[str, str]:
    host, _, site = slug.partition("/")
    if not host.endswith(".oraclecloud.com") or not site:
        raise BoardNotFound(f"oracle:{slug} (expected <pod>.oraclecloud.com/<siteNumber>)")
    return host, site


class OracleRecruiting:
    """Oracle Recruiting Cloud candidate-experience REST API (public, used by the career site itself).

    The slug is "<pod host>/<site number>", e.g. efzu.fa.em2.oraclecloud.com/CX_1 (DTU); seeded by hand.
    """

    name = "oracle"
    provides_name = False

    def __init__(self, detail_budget: int = DETAIL_BUDGET) -> None:
        self._budget = DetailBudget(detail_budget)

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        host, site = _split(slug)
        listing = await self._list(http, host, site)
        if listing is None:
            raise BoardNotFound(f"oracle:{slug}")
        postings = []
        for it in listing:
            rid = str(it["Id"])
            new = f"{self.name}:{slug}:{rid}" not in known_ids and self._budget.take()
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=rid, title=(it.get("Title") or "").strip(),
                url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
                description=await self._description(http, host, site, rid) if new else None,
                location_raw=it.get("PrimaryLocation"), country=country_code(it.get("PrimaryLocationCountry")),
                remote=infer_remote(it.get("WorkplaceType")), posted_at=it.get("PostedDate"),
            ))
        return postings

    async def _list(self, http: Http, host: str, site: str) -> list[dict] | None:
        """All requisitions on the site, or None when the site number does not exist."""
        items: list[dict] = []
        offset = 0
        while True:
            resp = await http.get(f"https://{host}{API}/recruitingCEJobRequisitions", params={
                "onlyData": "true", "expand": "requisitionList",
                "finder": f"findReqs;siteNumber={site},limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC",
            })
            if resp.status_code in (400, 404):
                return None
            resp.raise_for_status()
            search = (resp.json().get("items") or [None])[0]
            if search is None:
                return None
            page = search.get("requisitionList") or []
            items += page
            offset += len(page)  # the server may cap the page below PAGE_SIZE
            if not page or offset >= (search.get("TotalJobsCount") or 0):
                return items

    async def _description(self, http: Http, host: str, site: str, rid: str) -> str:
        resp = await http.get(f"https://{host}{API}/recruitingCEJobRequisitionDetails", params={
            "onlyData": "true", "expand": "all", "finder": f'ById;Id="{rid}",siteNumber={site}'})
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        detail = (resp.json().get("items") or [{}])[0]
        texts = [html_to_text(detail.get(key)) for key in SECTIONS]
        return "\n".join(t for t in texts if t)

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        try:
            host, site = _split(slug)
        except BoardNotFound:
            return ProbeResult(False)
        return ProbeResult(await self._list(http, host, site) is not None)
