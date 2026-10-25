import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.breezy import Breezy

URL = "https://soko-glam.breezy.hr/json"
P1 = "https://soko-glam.breezy.hr/p/017bb72a4933-intern-social-media"
P2 = "https://soko-glam.breezy.hr/p/fafbbeb107f0-paid-media-contractor"
COMPANY = {"name": "Soko Glam", "logo_url": None, "friendly_id": "soko-glam", "isMultipleLocationsEnabled": False}
LOC = {"country": {"name": "United States", "id": "US"}, "state": {"id": "NY", "name": "New York"},
       "city": "Brooklyn", "primary": True, "is_remote": False, "name": "Brooklyn, NY"}
INTERN = {"id": "017bb72a4933", "friendly_id": "017bb72a4933-intern-social-media", "name": "Intern, Social Media",
          "url": P1, "published_date": "2026-10-19T19:06:27.080Z", "type": {"id": "temporary", "name": "Temporary"},
          "location": LOC, "department": None, "salary": "$17 / hour", "company": COMPANY}
CONTRACTOR = {**INTERN, "id": "fafbbeb107f0", "friendly_id": "fafbbeb107f0-paid-media-contractor",
              "name": "Paid Media Contractor", "url": P2, "published_date": "2026-10-24T14:02:11.512Z",
              "location": {**LOC, "is_remote": True,
                           "remote_details": {"value": "remote", "label": "Fully remote, no location restrictions"}}}
JSONLD_PAGE = """<html><head>
<script type="application/ld+json">{"@context": "http://schema.org", "@type": "WebSite", "name": "Breezy HR"}</script>
<script type="application/ld+json">{"@context": "https://schema.org/", "@type": "JobPosting",
 "title": "Intern, Social Media", "datePosted": "2026-10-19",
 "description": "<p><strong>Position</strong>: Intern, Social Media<br>Visa sponsorship is not available.</p>",
 "hiringOrganization": {"@type": "Organization", "name": "Soko Glam"}}</script>
</head><body><div class="description"><p>ignored</p></div></body></html>"""
PLAIN_PAGE = """<html><body><div class="description"><h2>About</h2>
<p>We're a venture studio.</p></div><div class="apply-container"><a href="/apply">Apply</a></div></body></html>"""


async def test_parses_positions_and_descriptions(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json=[INTERN, CONTRACTOR]))
    respx_mock.get(P1).mock(return_value=httpx.Response(200, text=JSONLD_PAGE))
    respx_mock.get(P2).mock(return_value=httpx.Response(200, text=PLAIN_PAGE))
    p1, p2 = await Breezy().fetch(http, "soko-glam")
    assert (p1.id, p1.title, p1.url, p1.location_raw, p1.country, p1.remote, p1.posted_at) == (
        "breezy:soko-glam:017bb72a4933", "Intern, Social Media", P1, "Brooklyn, NY", "US", None, "2026-10-19")
    assert p1.description == "Position: Intern, Social Media\nVisa sponsorship is not available."
    assert (p2.remote, p2.posted_at, p2.description) == ("remote", "2026-10-24", "About\nWe're a venture studio.")


async def test_skips_detail_for_known_and_survives_closed_position(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json=[INTERN, CONTRACTOR]))
    respx_mock.get(P2).mock(return_value=httpx.Response(302, headers={"Location": "https://soko-glam.breezy.hr/"}))
    detail = respx_mock.get(P1)
    p1, p2 = await Breezy().fetch(http, "soko-glam", known_ids=frozenset({"breezy:soko-glam:017bb72a4933"}))
    assert not detail.called
    assert (p1.description, p2.description) == (None, "")


async def test_missing_and_unsafe_slugs(http, respx_mock):
    respx_mock.get("https://nope.breezy.hr/json").mock(return_value=httpx.Response(
        404, text="<!DOCTYPE html><title>Career portal not found | Breezy HR</title>"))
    with pytest.raises(BoardNotFound):
        await Breezy().fetch(http, "nope")
    assert (await Breezy().probe(http, "nope")).exists is False
    respx_mock.get("https://moved.breezy.hr/json").mock(return_value=httpx.Response(200, text="<html>Breezy HR</html>"))
    assert (await Breezy().probe(http, "moved")).exists is False
    respx_mock.get("https://gone.breezy.hr/json").mock(return_value=httpx.Response(301, headers={"Location": "https://breezy.hr/"}))
    with pytest.raises(BoardNotFound):
        await Breezy().fetch(http, "gone")
    assert (await Breezy().probe(http, "evil.example.com/x")).exists is False  # never builds a hostile host
    with pytest.raises(BoardNotFound):
        await Breezy().fetch(http, "Bad_Slug")


async def test_probe_existing(http, respx_mock):
    respx_mock.get("https://hello-viki.breezy.hr/json").mock(return_value=httpx.Response(200, json=[]))
    assert (await Breezy().probe(http, "hello-viki")).exists is True


async def test_detail_budget_defers_new_positions(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json=[INTERN, CONTRACTOR]))
    respx_mock.get(P1).mock(return_value=httpx.Response(200, text=JSONLD_PAGE))
    p1, p2 = await Breezy(detail_budget=1).fetch(http, "soko-glam")
    assert p1.description and p2.description is None
