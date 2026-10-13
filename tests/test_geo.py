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
