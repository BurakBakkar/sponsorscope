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


async def test_country_fragment_overrides_domain_and_is_not_sent(http, respx_mock):
    route = respx_mock.get("https://uu.varbi.com/en/what:rssfeed/").mock(return_value=httpx.Response(200, content=feed(
        f"""<item><title>Doktorand i datavetenskap</title><link>https://uu.varbi.com/en/what:job/jobID:1/</link>
        <guid>https://uu.varbi.com/en/what:job/jobID:1/</guid><description>x</description></item>""")))
    [p] = await UniversityRss().fetch(http, "uu.varbi.com/en/what:rssfeed/#country=SE")
    assert p.country == "SE" and p.level == "phd" and route.called
    assert UniversityRss.country_for("uu.varbi.com/en/what:rssfeed/#country=se") == "SE"


async def test_successfactors_escaped_description_and_plain_guid(http, respx_mock):
    respx_mock.get("https://careers.example.nl/jobs.xml").mock(return_value=httpx.Response(200, content=feed(
        """<item><title>PhD Position Quantum Sensing (Delft, NL, 2628 CD)</title>
        <description><![CDATA[&lt;p&gt;We &lt;strong&gt;welcome&lt;/strong&gt; you &amp;amp; your team.&lt;/p&gt;]]></description>
        <link>https://careers.example.nl/job/Delft-PhD-Position-2628</link><guid>1374333157</guid></item>""")))
    [p] = await UniversityRss().fetch(http, "careers.example.nl/jobs.xml")
    assert p.job_id == "1374333157" and p.country == "NL" and p.posted_at is None
    assert p.description == "We welcome you & your team."


async def test_broken_item_link_is_rebuilt_from_the_feed_url(http, respx_mock):
    broken = "https://cms.ku.dkObvius::Document=HASH(0x55b0f15de528)?show=170888"
    respx_mock.get("https://employment.ku.dk/all-vacancies/?get_rss=1").mock(return_value=httpx.Response(200, content=feed(
        f"<item><title>PhD fellowship in ecology</title><link>{broken}</link><guid>{broken}</guid>"
        "<description>x</description></item>")))
    [p] = await UniversityRss().fetch(http, "employment.ku.dk/all-vacancies/?get_rss=1")
    assert p.url == "https://employment.ku.dk/all-vacancies/?show=170888" and p.job_id == "170888"


async def test_rss_1_0_feed(http, respx_mock):
    rdf = b"""<?xml version="1.0" ?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns="http://purl.org/rss/1.0/">
  <channel rdf:about="https://utwentecareers.nl/en/vacancies/"><title>Vacancies</title></channel>
  <item rdf:about="https://utwentecareers.nl/en/vacancies/#2640">
    <title>PhD Position on Soft Robotics</title>
    <link>https://utwentecareers.nl/en/vacancies/2640/phd-position-soft-robotics/</link>
    <description>Join our lab.</description><dc:date>Mon, 19 Oct 2026 22:00:00 GMT</dc:date>
  </item>
</rdf:RDF>"""
    respx_mock.get("https://utwentecareers.nl/en/vacancies/rss/").mock(return_value=httpx.Response(200, content=rdf))
    [p] = await UniversityRss().fetch(http, "utwentecareers.nl/en/vacancies/rss/")
    assert (p.title, p.country, p.posted_at, p.description) == ("PhD Position on Soft Robotics", "NL", "2026-10-19", "Join our lab.")
    assert p.url.endswith("/2640/phd-position-soft-robotics/")
