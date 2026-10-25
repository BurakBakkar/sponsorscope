import httpx

from sponsorscope.discovery.seeds import (
    CONORS_URL, FEASHLIAA_URL, OPENROLES_URL, Seed, fetch_remote_seeds, load_manual, one_site_per_tenant, parse_conors, pick_workday_site,
    parse_feashliaa, parse_openroles,
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
    assert parse_openroles("recruitee", data) == [Seed("recruitee", "bunq", None)]


def test_workday_seeds_become_host_and_site_slugs():
    assert parse_feashliaa("workday", ["23andme|wd5|23", "Acme|WD1|External_Careers", "bad|wd1", "x|y|z"]) == [
        Seed("workday", "23andme.wd5.myworkdayjobs.com/23", None),
        Seed("workday", "acme.wd1.myworkdayjobs.com/external_careers", None)]
    data = [{"ats": "workday", "slug": "acme", "status": "live",
             "metadata": {"host": "acme.wd1.myworkdayjobs.com", "site": "External"}},
            {"ats": "workday", "slug": "nosite", "status": "live", "metadata": {"host": "nosite.wd1.myworkdayjobs.com"}},
            {"ats": "workday", "slug": "evil", "status": "live", "metadata": {"host": "evil.example.com", "site": "x"}}]
    assert parse_openroles("workday", data) == [Seed("workday", "acme.wd1.myworkdayjobs.com/external", None)]


def test_oracle_seeds_use_pod_host_and_site_number():
    data = [{"ats": "oraclecloud", "slug": "vertiv", "display_name": "Vertiv", "status": "live",
             "metadata": {"host": "egup.fa.us2.oraclecloud.com", "site": "CX"}},
            {"ats": "oraclecloud", "slug": "x", "status": "live", "metadata": {"host": "evil.com", "site": "CX"}}]
    assert parse_openroles("oracle", data) == [Seed("oracle", "egup.fa.us2.oraclecloud.com/CX", "Vertiv")]


def test_one_site_per_tenant_keeps_hand_seeded_sites():
    seeds = [Seed("workday", "acme.wd1.myworkdayjobs.com/internal", None),
             Seed("workday", "acme.wd1.myworkdayjobs.com/external", None),
             Seed("workday", "big.wd3.myworkdayjobs.com/careers", "Big"),
             Seed("workday", "big.wd3.myworkdayjobs.com/brand", "Big Brand"),
             Seed("workday", "big.wd3.myworkdayjobs.com/other", None),
             Seed("lever", "x", None)]
    assert set(one_site_per_tenant(seeds)) == {
        Seed("workday", "acme.wd1.myworkdayjobs.com/external", None), Seed("workday", "big.wd3.myworkdayjobs.com/careers", "Big"),
        Seed("workday", "big.wd3.myworkdayjobs.com/brand", "Big Brand"), Seed("lever", "x", None)}


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


def test_pick_workday_site_prefers_the_public_site():
    assert pick_workday_site(["external", "internal"]) == "external"
    assert pick_workday_site(["alexion", "broadbean_external", "careers", "emerging-talent"]) == "careers"
    assert pick_workday_site(["broadbean_external", "internaljobs", "pfizercareers"]) == "pfizercareers"
    assert pick_workday_site(["nvidiaexternalcareersite", "nvidiaexternalcareersitehardware"]) == "nvidiaexternalcareersite"
    assert pick_workday_site(["campus", "global"]) == "global"
    assert pick_workday_site(["international_careers", "us"]) == "international_careers"
