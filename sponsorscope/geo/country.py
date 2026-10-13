from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import pycountry

CITIES_PATH = Path(__file__).parent / "data" / "cities.tsv"

_US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
    "washington dc", "washington d.c.",
]
_CA_PROVINCES = [
    "alberta", "british columbia", "manitoba", "new brunswick", "newfoundland and labrador",
    "nova scotia", "ontario", "prince edward island", "quebec", "québec", "saskatchewan",
    "northwest territories", "nunavut", "yukon",
]
_EXTRA = {
    "uk": "GB", "u.k.": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "great britain": "GB", "britain": "GB",
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "deutschland": "DE",
    "czech republic": "CZ", "south korea": "KR", "korea": "KR", "russia": "RU", "vietnam": "VN",
    "turkey": "TR", "türkiye": "TR", "uae": "AE", "taiwan": "TW", "iran": "IR", "bolivia": "BO",
    "venezuela": "VE", "tanzania": "TZ", "syria": "SY", "laos": "LA", "moldova": "MD",
    **{s: "US" for s in _US_STATES},  # overrides the country Georgia on purpose
    **{p: "CA" for p in _CA_PROVINCES},
}

_SPLIT = re.compile(r"[,/|;()\n]+|\s[-–]\s")


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for c in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            value = getattr(c, attr, None)
            if value:
                names[value.lower()] = c.alpha_2
    names.update(_EXTRA)
    return names


@lru_cache(maxsize=1)
def _codes() -> tuple[frozenset[str], dict[str, str]]:
    alpha2 = frozenset(c.alpha_2 for c in pycountry.countries)
    alpha3 = {c.alpha_3: c.alpha_2 for c in pycountry.countries}
    return alpha2, alpha3


@lru_cache(maxsize=1)
def load_cities(path: Path = CITIES_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row[0]: row[1] for row in csv.reader(f, delimiter="\t") if len(row) == 2}


def resolve_country(location_raw: str | None, structured: str | None = None,
                    cities: Mapping[str, str] | None = None) -> str | None:
    """Best-effort ISO-2 country for a posting; None when unknown or ambiguous.

    Evidence tiers, strongest first: country/state names, city names, bare codes.
    The first tier with any hit decides; more than one country in it means None.
    """
    alpha2, alpha3 = _codes()
    if structured and structured.strip().upper() in alpha2:
        return structured.strip().upper()
    if not location_raw:
        return None
    cities = load_cities() if cities is None else cities
    names = _country_names()
    tiers: list[set[str]] = [set(), set(), set()]
    for segment in _SPLIT.split(location_raw):
        token = segment.strip()
        if not token:
            continue
        low = token.lower()
        if low in names:
            tiers[0].add(names[low])
        elif low in cities:
            tiers[1].add(cities[low])
        elif token.isupper() and token in alpha2:
            tiers[2].add(token)
        elif token.isupper() and token in alpha3:
            tiers[2].add(alpha3[token])
    for tier in tiers:
        if len(tier) == 1:
            return next(iter(tier))
        if len(tier) > 1:
            return None
    return None
