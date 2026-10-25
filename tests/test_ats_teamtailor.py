import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.teamtailor import Teamtailor

URL = "https://opply-1682428990.teamtailor.com/jobs.rss"
RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel>
    <title>Opply</title>
    <description>Job openings</description>
    <link>https://opply-1682428990.teamtailor.com/jobs</link>
    <item>
      <title>Supplier Partnerships Manager - US</title>
      <description>&lt;p&gt;Join &lt;strong&gt;Opply&lt;/strong&gt;.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Visa sponsorship available&lt;/li&gt;&lt;/ul&gt;</description>
      <pubDate>Tue, 18 Aug 2026 14:22:36 +0100</pubDate>
      <link>https://opply-1682428990.teamtailor.com/jobs/8236221-supplier-partnerships-manager-us</link>
      <remoteStatus>hybrid</remoteStatus>
      <guid>ee9b7fe2-103d-4ccf-83aa-eaeed4741b85</guid>
      <tt:locations>
        <tt:location>
          <tt:name>Chicago</tt:name><tt:address/><tt:zip/>
          <tt:city>Chicago</tt:city><tt:country>United States</tt:country>
        </tt:location>
      </tt:locations>
      <tt:department>Supply</tt:department>
      <tt:role/>
    </item>
    <item>
      <title>Design Director</title>
      <description>&lt;p&gt;Lead design.&lt;/p&gt;</description>
      <pubDate>Fri, 09 Oct 2026 13:50:03 +0800</pubDate>
      <link>https://careers.hba.com/jobs/8520686-design-director</link>
      <remoteStatus>none</remoteStatus>
      <guid>a12c440c-0933-4c40-8dd0-7502b782be51</guid>
      <tt:locations>
        <tt:location>
          <tt:name>London</tt:name><tt:address>26 Westbourne Grove</tt:address><tt:zip>W2 5RH</tt:zip>
          <tt:city>London</tt:city><tt:country>United Kingdom</tt:country>
        </tt:location>
        <tt:location>
          <tt:name>Tokyo</tt:name><tt:address/><tt:zip/>
          <tt:city/><tt:country>Japan</tt:country>
        </tt:location>
      </tt:locations>
      <tt:department/>
      <tt:role/>
    </item>
  </channel>
</rss>"""
RSS_HEADERS = {"Content-Type": "application/rss+xml; charset=utf-8"}


async def test_parses_items(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text=RSS, headers=RSS_HEADERS))
    first, second = await Teamtailor().fetch(http, "opply-1682428990")
    assert (first.id, first.title, first.url, first.posted_at) == (
        "teamtailor:opply-1682428990:ee9b7fe2-103d-4ccf-83aa-eaeed4741b85", "Supplier Partnerships Manager - US",
        "https://opply-1682428990.teamtailor.com/jobs/8236221-supplier-partnerships-manager-us", "2026-08-18")
    assert (first.location_raw, first.country, first.remote) == ("Chicago, United States", "US", "hybrid")
    assert first.description == "Join Opply.\nVisa sponsorship available"
    assert (second.location_raw, second.country, second.remote, second.posted_at) == (
        "London, United Kingdom; Tokyo, Japan", None, None, "2026-10-09")


async def test_missing_and_unsafe_slugs(http, respx_mock):
    respx_mock.get("https://nope.teamtailor.com/jobs.rss").mock(
        return_value=httpx.Response(404, text="<html>404</html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(BoardNotFound):
        await Teamtailor().fetch(http, "nope")
    assert (await Teamtailor().probe(http, "nope")).exists is False
    assert (await Teamtailor().probe(http, "evil.example.com/x")).exists is False  # never builds a hostile host
    with pytest.raises(BoardNotFound):
        await Teamtailor().fetch(http, "Bad_Slug")


async def test_probe_existing(http, respx_mock):
    empty = '<?xml version="1.0"?><rss version="2.0"><channel><title>Opply</title></channel></rss>'
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text=empty, headers=RSS_HEADERS))
    result = await Teamtailor().probe(http, "opply-1682428990")
    assert result.exists is True and result.name is None
    assert await Teamtailor().fetch(http, "opply-1682428990") == []
