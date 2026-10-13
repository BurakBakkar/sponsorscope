import httpx

from sponsorscope.discovery.seeds import (
    CONORS_URL, FEASHLIAA_URL, Seed, fetch_remote_seeds, load_manual, parse_conors, parse_feashliaa,
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
    seeds, errors = await fetch_remote_seeds(http, {"greenhouse", "lever", "ashby", "recruitee"})
    assert set(seeds) == {Seed("greenhouse", "airbnb", None), Seed("ashby", "notion", None), Seed("recruitee", "bunq", "bunq")}
    assert len(errors) == 1 and "lever" in errors[0]
