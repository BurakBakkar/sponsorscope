import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.personio import Personio

URL = "https://tado.jobs.personio.de/xml"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
  <position>
    <id>1234</id><name> Backend Engineer </name><office>Germany - Munich</office>
    <additionalOffices><office>Remote</office></additionalOffices>
    <jobDescriptions>
      <jobDescription><name>Your role</name><value><![CDATA[<p>Build <b>APIs</b>.</p>]]></value></jobDescription>
      <jobDescription><name>Perks</name><value><![CDATA[<p>We offer visa sponsorship.</p>]]></value></jobDescription>
    </jobDescriptions>
    <createdAt>2026-10-13T09:59:49+00:00</createdAt>
  </position>
  <position><id>99</id><name>Empty</name><office>Berlin</office><jobDescriptions/></position>
</workzag-jobs>"""
BOMB = """<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
<workzag-jobs><position><id>1</id><name>&lol2;</name></position></workzag-jobs>"""


async def test_parses_positions(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text=XML, headers={"Content-Type": "text/xml"}))
    first, second = await Personio().fetch(http, "tado")
    assert (first.id, first.title, first.url, first.posted_at) == (
        "personio:tado:1234", "Backend Engineer", "https://tado.jobs.personio.de/job/1234", "2026-10-13")
    assert first.location_raw == "Germany - Munich; Remote" and first.remote == "remote" and first.country is None
    assert first.description == "Your role\nBuild APIs.\nPerks\nWe offer visa sponsorship."
    assert second.description == "" and second.posted_at is None


async def test_html_404_and_non_xml_200_are_not_boards(http, respx_mock):
    respx_mock.get("https://nope.jobs.personio.de/xml").mock(return_value=httpx.Response(404, text="<html>Page Not Found</html>"))
    respx_mock.get("https://html.jobs.personio.de/xml").mock(
        return_value=httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(BoardNotFound):
        await Personio().fetch(http, "nope")
    assert (await Personio().probe(http, "nope")).exists is False
    assert (await Personio().probe(http, "html")).exists is False
    with pytest.raises(BoardNotFound):
        await Personio().fetch(http, "html")


async def test_entity_expansion_is_rejected(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text=BOMB, headers={"Content-Type": "text/xml"}))
    with pytest.raises(Exception, match="(?i)entit"):
        await Personio().fetch(http, "tado")
