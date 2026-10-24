import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.oracle import OracleRecruiting

HOST = "efzu.fa.em2.oraclecloud.com"
SLUG = f"{HOST}/CX_1"
LIST = f"https://{HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL = f"https://{HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"


def req(i, title):
    return {"Id": str(i), "Title": title, "PostedDate": "2026-10-23", "PrimaryLocation": "Kgs. Lyngby, Denmark",
            "PrimaryLocationCountry": "DK", "WorkplaceType": ""}


def page(items, total):
    return {"items": [{"TotalJobsCount": total, "requisitionList": items}]}


async def test_lists_pages_and_fetches_details_for_new_postings_only(http, respx_mock):
    listing = respx_mock.get(LIST).mock(side_effect=[
        httpx.Response(200, json=page([req(1, "PhD scholarship in Wind Energy"), req(2, "Postdoc in Optics")], 3)),
        httpx.Response(200, json=page([req(3, "Head of Finance")], 3)),
    ])
    detail = respx_mock.get(DETAIL).mock(return_value=httpx.Response(200, json={"items": [{
        "ExternalDescriptionStr": "<p>We offer <b>visa support</b>.</p>",
        "ExternalResponsibilitiesStr": "<ul><li>Research</li></ul>", "ExternalQualificationsStr": ""}]}))
    known = frozenset({f"oracle:{SLUG}:2", f"oracle:{SLUG}:3"})
    phd, postdoc, head = await OracleRecruiting().fetch(http, SLUG, known_ids=known)

    assert "siteNumber=CX_1" in listing.calls[0].request.url.params["finder"]
    assert "offset=2" in listing.calls[1].request.url.params["finder"]
    assert detail.call_count == 1 and 'Id="1"' in detail.calls[0].request.url.params["finder"]
    assert (phd.id, phd.title, phd.country, phd.posted_at, phd.location_raw) == (
        f"oracle:{SLUG}:1", "PhD scholarship in Wind Energy", "DK", "2026-10-23", "Kgs. Lyngby, Denmark")
    assert phd.url == f"https://{HOST}/hcmUI/CandidateExperience/en/sites/CX_1/job/1"
    assert phd.description == "We offer visa support.\nResearch"
    assert postdoc.description is None and head.description is None


async def test_unknown_site_raises(http, respx_mock):
    respx_mock.get(LIST).mock(return_value=httpx.Response(200, json={"items": []}))
    with pytest.raises(BoardNotFound):
        await OracleRecruiting().fetch(http, SLUG)
    with pytest.raises(BoardNotFound):
        await OracleRecruiting().fetch(http, "not-a-slug")
