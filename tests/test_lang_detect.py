from sponsorscope.classify.lang_detect import is_english

EN = ("We are looking for a backend engineer to join our payments team in London. "
      "You will design and build reliable services used by millions of customers.")
NL = ("Wij zoeken een ervaren backend ontwikkelaar voor ons betalingsteam in Amsterdam. "
      "Je bouwt betrouwbare diensten die door miljoenen klanten worden gebruikt.")
DE = ("Wir suchen eine erfahrene Backend-Entwicklerin für unser Zahlungsteam in Berlin. "
      "Du entwickelst zuverlässige Dienste, die von Millionen Kunden genutzt werden.")


def test_detects_english():
    assert is_english(EN)


def test_rejects_dutch_and_german():
    assert not is_english(NL)
    assert not is_english(DE)


def test_short_text_is_kept_rather_than_silently_dropped():
    assert is_english("Data Engineer")
    assert is_english("Ingenieur (m/w/d)")


def test_short_english_postings_above_cutoff_are_kept():
    # Greenhouse postings with null content are title-only or one line; lingua is unsure (<0.8) but still picks English
    assert is_english("Software Engineer\nJoin our platform team in London building APIs.")
    assert is_english("Senior Backend Engineer (Go, Kubernetes, AWS)")
    assert is_english("Data Engineer\nPython, SQL, Airflow, dbt, Snowflake, GCP.")


def test_short_non_english_is_still_rejected():
    assert not is_english("Ingenieur Softwareentwicklung (m/w/d) in Vollzeit")
