import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.successfactors import SuccessFactors, _location_country, parse_job, parse_search

HOST = "jobs.biontech.com"
ROBOTS = f"https://{HOST}/robots.txt"
SEARCH = f"https://{HOST}/search/"


def table_row(job_id, title, location):
    path = f"/job/{title.replace(' ', '-')}/{job_id}/"
    return f"""<tr class="data-row"><td class="colTitle">
      <span class="jobTitle hidden-phone"><a href="{path}" class="jobTitle-link">{title}</a></span>
      <div class="jobdetail-phone visible-phone"><span class="jobTitle visible-phone">
        <a class="jobTitle-link" href="{path}">{title}</a></span>
        <span class="jobLocation visible-phone"><span class="jobLocation">
            {location}
        </span></span></div></td>
      <td class="colLocation hidden-phone"><span class="jobLocation">{location}</span></td>
      <td class="colDate hidden-phone"><span class="jobDate">Oct 25, 2026</span></td></tr>"""


def table_page(rows, first, last, total):
    return f"""<html><body><span class="paginationLabel" aria-label="Results {first} – {last}">
      Results <b>{first} – {last}</b> of <b>{total}</b></span><table>{''.join(rows)}</table></body></html>"""


TILE_PAGE = """<html><body><div class="job-tile-result-container">
<span id="tile-search-results-label">Showing 1 to 1 of 1 Jobs</span>
<ul id="job-tile-list"><li class="job-tile job-id-1369651255" data-url="/job/Warren-Data-Engineer-NJ/1369651255/">
  <div class="tiletitle"><span class="section-title title">
    <a class="jobTitle-link" href="/job/Warren-Data-Engineer-NJ/1369651255/">
      Data Engineer
    </a></span></div>
  <div id="job-1369651255-desktop-section-location" class="section-field location">
    <span class="section-label">Location</span>
    <div id="job-1369651255-desktop-section-location-value">Warren, NJ, US
    </div></div></li></ul></div></body></html>"""

JOB_PAGE = """<html><body><div itemscope itemtype="http://schema.org/JobPosting">
<span itemprop="title">Director Safety Physician</span>
<span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
  <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
    <meta itemprop="addressLocality" content="Cambridge"><meta itemprop="addressCountry" content="US"></span></span>
<meta itemprop="datePosted" content="Sun Oct 25 02:00:00 UTC 2026">
<meta itemprop="hiringOrganization" content="BioNTech">
<span itemprop="description" class="rtltextaligneligible"><p>We sponsor H-1B visas.</p></span>
</div></body></html>"""

ROWS = [table_row(1399929333, "Director Safety Physician", "Cambridge, MA, US, MA 02139"),
        table_row(1420851833, "Senior Medical Science Liaison", "London, GB, NW1 3DX"),
        table_row(1437916433, "QC Analyst", "Gif-sur-Yvette, FR, 91190")]


@pytest.fixture
def allowed(respx_mock):
    respx_mock.get(ROBOTS).mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /services/\n"))


def test_parse_search_reads_both_layouts():
    rows, total = parse_search(table_page(ROWS[:2], 1, 2, 143))
    assert total == 143
    assert rows[0] == ("1399929333", "/job/Director-Safety-Physician/1399929333/", "Director Safety Physician",
                       "Cambridge, MA, US, MA 02139")
    assert parse_search(TILE_PAGE) == ([("1369651255", "/job/Warren-Data-Engineer-NJ/1369651255/", "Data Engineer",
                                         "Warren, NJ, US")], 1)


def test_country_from_location_text():
    assert [_location_country(x) for x in ["Cambridge, MA, US, MA 02139", "Taipei, Taipei City, TW, 10480",
                                           "Switzerland", "Fall River, Mass", "Remote", None]] == [
        "US", "TW", "CH", None, None, None]


def test_job_page_location_when_the_list_has_none():
    page = """<span class="jobGeoLocation">Illkirch, FR</span>
    <span itemprop="address"><meta itemprop="streetAddress" content="Illkirch, FR"></span>"""
    assert parse_job(page)["location"] == "Illkirch, FR"
    page = """<meta itemprop="addressLocality" content="Fall River"><meta itemprop="addressRegion" content="Mass">"""
    assert parse_job(page)["location"] == "Fall River, Mass"


def test_brand_prefixed_job_paths():
    page = table_page([table_row(1431553133, "Clinical Trial Administrator", "Minneapolis, MN, US")], 1, 1, 1)
    page = page.replace('"/job/', '"/Kerecis/job/')
    assert parse_search(page)[0][0][:2] == ("1431553133", "/Kerecis/job/Clinical-Trial-Administrator/1431553133/")


async def test_pages_through_search_and_reads_new_job_pages(http, respx_mock, allowed):
    search = respx_mock.get(url__startswith=SEARCH).mock(side_effect=[
        httpx.Response(200, text=table_page(ROWS[:2], 1, 2, 3)),
        httpx.Response(200, text=table_page(ROWS[2:], 3, 3, 3)),
    ])
    job = respx_mock.get(f"https://{HOST}/job/Director-Safety-Physician/1399929333/").mock(
        return_value=httpx.Response(200, text=JOB_PAGE))
    gone = respx_mock.get(f"https://{HOST}/job/QC-Analyst/1437916433/").mock(
        return_value=httpx.Response(302, headers={"location": "/search/"}))
    known = frozenset({f"successfactors:{HOST}:1420851833"})
    postings = await SuccessFactors().fetch(http, HOST, known_ids=known)

    assert [c.request.url.params["startrow"] for c in search.calls] == ["0", "2"]
    assert job.call_count == 1 and gone.call_count == 1
    first, known_one, closed = postings
    assert (first.id, first.title, first.url, first.country, first.posted_at, first.description) == (
        f"successfactors:{HOST}:1399929333", "Director Safety Physician",
        f"https://{HOST}/job/Director-Safety-Physician/1399929333/", "US", "2026-10-25", "We sponsor H-1B visas.")
    assert known_one.description is None and known_one.country == "GB"  # no job page: country from the location
    assert closed.description == "" and closed.country == "FR"


async def test_detail_budget_leaves_the_rest_for_later_runs(http, respx_mock, allowed):
    respx_mock.get(url__startswith=SEARCH).mock(return_value=httpx.Response(200, text=table_page(ROWS, 1, 3, 3)))
    job = respx_mock.get(url__startswith=f"https://{HOST}/job/").mock(return_value=httpx.Response(200, text=JOB_PAGE))
    postings = await SuccessFactors(detail_budget=1).fetch(http, HOST)
    assert job.call_count == 1 and [p.description is None for p in postings] == [False, True, True]


async def test_robots_disallowed_site_is_not_crawled(http, respx_mock):
    respx_mock.get(ROBOTS).mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /search/\n"))
    search = respx_mock.get(url__startswith=SEARCH)
    with pytest.raises(BoardNotFound, match="robots"):
        await SuccessFactors().fetch(http, HOST)
    assert not search.called


async def test_unknown_site_and_bad_slug(http, respx_mock, allowed):
    respx_mock.get(url__startswith=SEARCH).mock(return_value=httpx.Response(404))
    with pytest.raises(BoardNotFound):
        await SuccessFactors().fetch(http, HOST)
    with pytest.raises(BoardNotFound):
        await SuccessFactors().fetch(http, "https://jobs.biontech.com/search")
    assert not (await SuccessFactors().probe(http, HOST)).exists
