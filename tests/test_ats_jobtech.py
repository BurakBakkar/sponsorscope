import httpx

from sponsorscope.ats.jobtech import DOCTORAL, JobTech

SEARCH = "https://jobsearch.api.jobtechdev.se/search"


def hit(i, headline, group=DOCTORAL, employer="Linköpings universitet"):
    return {"id": str(i), "headline": headline, "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{i}",
            "description": {"text": "Welcome to apply. We help with the residence permit."},
            "employer": {"name": employer, "organization_number": "2021003096"},
            "occupation_group": {"concept_id": group, "label": "Doktorander"},
            "workplace_address": {"municipality": "Norrköping", "region": "Östergötlands län", "country": "Sverige"},
            "publication_date": "2026-10-23T12:59:02", "workplace_model": {"label": None}}


async def test_runs_each_query_and_merges_hits_by_id(http, respx_mock):
    def respond(request):
        params = request.url.params
        if params.get("occupation-group") == DOCTORAL:
            hits = [hit(1, "PhD student in materials science"), hit(2, "Doktorand i fysik")]
            return httpx.Response(200, json={"total": {"value": 2}, "hits": hits[int(params["offset"]):]})
        return httpx.Response(200, json={"total": {"value": 2}, "hits": [
            hit(2, "Doktorand i fysik"), hit(3, "Master thesis: battery analytics", group="x", employer="Volvo Cars"),
            hit(4, "Senior Data Scientist (PhD required)", group="x", employer="Spotify")]})

    route = respx_mock.get(SEARCH).mock(side_effect=respond)
    postings = await JobTech().fetch(http, f"occupation-group={DOCTORAL}|q=thesis")
    by_id = {p.job_id: p for p in postings}
    assert sorted(by_id) == ["1", "2", "3"] and route.call_count == 2
    phd = by_id["1"]
    assert (phd.id, phd.employer, phd.level, phd.country, phd.posted_at) == (
        f"jobtech:occupation-group={DOCTORAL}|q=thesis:1", "Linköpings universitet", "phd", "SE", "2026-10-23")
    assert phd.location_raw == "Norrköping, Östergötlands län" and phd.url.endswith("/annonser/1")
    assert phd.description == "Welcome to apply. We help with the residence permit."
    assert by_id["3"].level == "masters" and by_id["3"].employer == "Volvo Cars"
    assert "4" not in by_id  # an ordinary job that merely mentions a PhD
