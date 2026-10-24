import httpx

from sponsorscope.discovery.seeds import (
    CONORS_URL, FEASHLIAA_URL, OPENROLES_URL, Seed, fetch_remote_seeds, load_manual, parse_conors, parse_feashliaa,
    parse_openroles,
)


def test_parse_feashliaa_flat_slug_list():
    assert parse_feashliaa("lever", ["15five", " 10up-2 ", "", 7, None]) == [
        Seed("lever", "15five", None), Seed("lever", "10up-2", None)]


def test_parse_conors_filters_platforms_and_shapes():
    data = [{"name": "Stripe", "platform": "greenhouse", "slug": "stripe"},
            {"name": "Acme", "platform": "workday", "workday": {"tenant": "acme"}},
            {"name": "bunq", "platform": "recruitee", "slug": "bunq"},
            {"platform": "lever"}]
    assert parse_conors(data, {"greenhouse", "recruitee"}) == [
        Seed("greenhouse", "stripe", "Stripe"), Seed("recruitee", "bunq", "bunq")]


def test_parse_openroles_keeps_live_tenants_only():
    data = [{"ats": "recruitee", "slug": "bunq", "status": "live"},
            {"ats": "recruitee", "slug": "gone", "status": "dead"},
            {"ats": "recruitee", "slug": " ", "status": "live"}, "junk"]
    assert parse_openroles(data) == [Seed("recruitee", "bunq", None)]


def test_load_manual(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("- {ats: lever, slug: palantir, name: Palantir}\n")
    assert load_manual(path) == [Seed("lever", "palantir", "Palantir")]
    assert load_manual(tmp_path / "missing.yaml") == []


async def test_fetch_remote_seeds_tolerates_one_failing_source(http, respx_mock):
    respx_mock.get(FEASHLIAA_URL.format(ats="greenhouse")).mock(return_value=httpx.Response(200, json=["airbnb"]))
    respx_mock.get(FEASHLIAA_URL.format(ats="lever")).mock(return_value=httpx.Response(500))
    respx_mock.get(FEASHLIAA_URL.format(ats="ashby")).mock(return_value=httpx.Response(200, json=["notion"]))
    respx_mock.get(CONORS_URL).mock(return_value=httpx.Response(200, json=[{"name": "bunq", "platform": "recruitee", "slug": "bunq"}]))
    for ats in ("greenhouse", "lever", "ashby"):
        respx_mock.get(OPENROLES_URL.format(ats=ats)).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(OPENROLES_URL.format(ats="recruitee")).mock(
        return_value=httpx.Response(200, json=[{"ats": "recruitee", "slug": "sweco", "status": "live"}]))
    seeds, errors = await fetch_remote_seeds(http, {"greenhouse", "lever", "ashby", "recruitee"})
    assert set(seeds) == {Seed("greenhouse", "airbnb", None), Seed("ashby", "notion", None), Seed("recruitee", "bunq", "bunq"),
                          Seed("recruitee", "sweco", None)}
    assert len(errors) == 1 and "lever" in errors[0]
