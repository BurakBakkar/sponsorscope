import pytest

from sponsorscope.matching.names import Overrides, SponsorIndex, compact, find_match, normalize


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Booking.com B.V.", "booking com"),
        ("  ACME Widgets Limited ", "acme widgets"),
        ("Café Ünïcode GmbH", "cafe unicode"),
        ("Marks & Spencer PLC", "marks and spencer"),
        ("Monzo Bank Ltd", "monzo bank"),
        ("Adyen N.V.", "adyen"),
        ("Novo Nordisk A/S", "novo nordisk"),
        ("Wolt Enterprises Oy", "wolt enterprises"),
        ("Spotify AB", "spotify"),
        ("Acme Holdings Group Ltd", "acme"),
        ("Airbnb UK Ltd", "airbnb"),
        ('""Aa-Dee"" Services B.V.', "aa dee"),
        ("Ltd", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_compact_removes_spaces():
    assert compact("booking com") == "bookingcom"


def _index(*legal_names):
    return SponsorIndex.build((i, normalize(n)) for i, n in enumerate(legal_names, start=1))


INDEX = _index(
    "Booking.com B.V.",
    "Apple Retail UK Limited",
    "Monzo Bank Ltd",
    "IBM UK Ltd",
)


@pytest.mark.parametrize(
    "company, expected",
    [
        ("Booking.com", ("booking com", "exact")),
        ("Bookingcom", ("booking com", "normalised")),
        ("Monzo Bank", ("monzo bank", "exact")),
        ("Apple", None),  # "apple retail" is a different entity name
        ("Monzo", None),  # too far from "monzo bank" to auto-match
        ("IBM", None),  # short-name guard, even though "ibm" would match exactly
    ],
)
def test_find_match(company, expected):
    result = find_match(normalize(company), INDEX)
    if expected is None:
        assert result is None
    else:
        assert result is not None and result[:2] == expected


def test_fuzzy_match_requires_unique_candidate():
    one = _index("Northwind Global Trading Partners X Ltd")
    two = _index("Northwind Global Trading Partners X Ltd", "Northwind Global Trading Partners Y Ltd")
    company = normalize("Northwind Global Trading Partners")
    match = find_match(company, one)
    assert match is not None and match[1] == "normalised" and match[2] >= 95
    assert find_match(company, two) is None


def test_index_groups_ids_by_norm():
    idx = SponsorIndex.build([(1, "acme"), (2, "acme"), (3, "beta")])
    assert idx.by_norm["acme"] == [1, 2]
    assert sorted(idx.norms) == ["acme", "beta"]


def test_overrides_load_normalises(tmp_path):
    path = tmp_path / "overrides.yaml"
    path.write_text(
        "match:\n  - {company: Stripe, sponsor: Stripe Payments UK Ltd}\n"
        "forbid:\n  - {company: Apple, sponsor: Apple Ltd}\n"
    )
    o = Overrides.load(path)
    assert o.force == {("stripe", "stripe payments")}
    assert o.forbid == {("apple", "apple")}


def test_overrides_load_missing_or_empty_file(tmp_path):
    assert Overrides.load(tmp_path / "nope.yaml") == Overrides()
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert Overrides.load(empty) == Overrides()
