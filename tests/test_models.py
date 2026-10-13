from sponsorscope.models import Label, RawPosting, SponsorRecord, content_hash
from sponsorscope.text import html_to_text


def test_posting_id_combines_ats_slug_and_job():
    p = RawPosting(ats="lever", slug="acme", job_id="abc", title="t", url="u",
                   description="d", location_raw=None, country=None, remote=None, posted_at=None)
    assert p.id == "lever:acme:abc"


def test_content_hash_ignores_whitespace_and_case():
    assert content_hash("Hello   World\n") == content_hash("hello world")
    assert content_hash("hello world") != content_hash("hello there")


def test_sponsor_record_defaults():
    r = SponsorRecord(country="GB", source="gb", evidence="licence", legal_name="Acme Ltd")
    assert r.route is None and r.filings is None and r.period is None


def test_label_is_hashable_value():
    assert Label("yes", False, ("nl",), ("x",)) == Label("yes", False, ("nl",), ("x",))


def test_html_to_text_keeps_inline_words_together_and_breaks_blocks():
    html = "<p>We <strong>offer</strong> visa sponsorship.</p><ul><li>Fluent Dutch</li><li>German is a plus</li></ul>"
    assert html_to_text(html) == "We offer visa sponsorship.\nFluent Dutch\nGerman is a plus"


def test_html_to_text_handles_empty():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_html_to_text_normalises_non_breaking_spaces():
    # "visa&nbsp;sponsorship" must still match the classifier's "visa sponsorship" rules
    assert html_to_text("<p>We offer visa&nbsp;sponsorship&#xa0;now</p>") == "We offer visa sponsorship now"
