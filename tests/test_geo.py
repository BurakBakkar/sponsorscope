import pytest

from sponsorscope.geo.country import resolve_country

CITIES = {
    "london": "GB", "amsterdam": "NL", "san francisco": "US", "toronto": "CA", "berlin": "DE",
    "atlanta": "US", "paris": "FR", "munich": "DE",
}


@pytest.mark.parametrize(
    "location, structured, expected",
    [
        ("London, UK", None, "GB"),
        ("Amsterdam / Remote (EU)", None, "NL"),
        ("Remote", None, None),
        ("San Francisco, CA", None, "US"),  # CA is California here, not Canada
        ("Toronto, ON", None, "CA"),
        ("Berlin, DE", None, "DE"),
        ("Remote - US", None, "US"),
        ("London, Ontario, Canada", None, "CA"),  # country name beats city
        ("Atlanta, Georgia", None, "US"),  # US state, not the country
        ("New York, NY", None, "US"),
        ("Berlin, Germany", None, "DE"),
        ("Munich, Germany; Remote", None, "DE"),
        ("London or Berlin", None, None),
        ("London; Berlin", None, None),  # two countries → unknown
        (None, "gb", "GB"),
        ("Paris", "EU", "FR"),  # invalid structured code falls back to text
        (None, None, None),
        ("", None, None),
    ],
)
def test_resolve_country(location, structured, expected):
    assert resolve_country(location, structured, cities=CITIES) == expected


from sponsorscope.geo.country import load_cities


def test_bundled_city_table_resolves_major_cities():
    cities = load_cities()
    assert cities["london"] == "GB" and cities["amsterdam"] == "NL"
    assert resolve_country("Dublin") == "IE"


GB_HEAVY = {**CITIES, "cambridge": "GB", "manchester": "GB", "birmingham": "GB", "mumbai": "IN", "rabat": "MA"}


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Cambridge, MA", "US"),  # state code beats a same-named UK city
        ("London, ON", "CA"),  # province code
        ("Manchester, NH", "US"),
        ("Birmingham, AL", "US"),
        ("Paris, TX", "US"),
        ("Berlin, DE", "DE"),  # DE is also Delaware, but agrees with the city → country code
        ("Mumbai, IN", "IN"),  # IN is also Indiana
        ("Rabat, MA", "MA"),  # MA is also Massachusetts
        ("Amsterdam, NL", "NL"),  # NL is also Newfoundland
    ],
)
def test_state_and_province_codes(location, expected):
    assert resolve_country(location, cities=GB_HEAVY) == expected
