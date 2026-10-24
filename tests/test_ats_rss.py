import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.rss import UniversityRss

SLUG = "jobs.example.ac.uk/rss/rss.aspx"
URL = f"https://{SLUG}"


def item(title, ref, category="Research", pub="Tue, 13 Oct 2026 00:00:00 GMT"):
    return f"""<item>
      <title>{title}</title>
      <link>https://jobs.example.ac.uk/rss/click.aspx?ref={ref}</link>
      <guid>https://jobs.example.ac.uk/rss/click.aspx?ref={ref}</guid>
      <description>&lt;p&gt;International students are welcome; we can sponsor a &lt;b&gt;Student visa&lt;/b&gt;.&lt;/p&gt;</description>
      <category>{category}</category>
      <pubDate>{pub}</pubDate>
    </item>"""


def feed(*items):
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<!-- Do not remove, space added for FireFox bug -->
<?xml-stylesheet title="XSL_formatting" type="text/xsl" href="/rss/rss.xslt"?>
<rss version="2.0"><channel><title>Jobs at Example</title>{"".join(items)}</channel></rss>""".encode()


async def test_keeps_only_degree_offers(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, content=feed(
        item("PhD Studentship: Soil &amp;amp; Water (GS-12)", "GS-12"),
        item("Postdoctoral Research Associate (SS1)", "SS1"),
        item("Funded projects 2027", "GS-13", category="Research Degree Studentships"),
    )))
    phd, by_category = await UniversityRss().fetch(http, SLUG)
    assert (phd.id, phd.title, phd.level, phd.country, phd.posted_at) == (
        f"rss:{SLUG}:GS-12", "PhD Studentship: Soil & Water (GS-12)", "phd", "GB", "2026-10-13")
    assert phd.url == "https://jobs.example.ac.uk/rss/click.aspx?ref=GS-12"
    assert phd.description == "International students are welcome; we can sponsor a Student visa."
    assert by_category.job_id == "GS-13" and by_category.level == "phd"


async def test_country_from_domain():
    assert UniversityRss.country_for("jobs.example.ac.uk/rss/rss.aspx") == "GB"
    assert UniversityRss.country_for("werkenbij.example.nl/rss") == "NL"
    assert UniversityRss.country_for("jobs.example.com/feed") is None


async def test_missing_feed_raises(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(BoardNotFound):
        await UniversityRss().fetch(http, SLUG)
    assert (await UniversityRss().probe(http, SLUG)).exists is False
