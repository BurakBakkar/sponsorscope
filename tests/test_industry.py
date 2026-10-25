import pytest

from sponsorscope.classify.industry import BIOTECH, biotech_naics, detect_industry
from sponsorscope.classify.rules import RulesClassifier

BIOTECH_TEXTS = [
    "Moderna is a clinical-stage biotechnology company pioneering mRNA medicines.",
    "Genmab is an international biotech company specialising in bispecific antibodies.",
    "Join our process development team scaling up cGMP manufacturing of biologics.",
    "As a Scientist you will run assays supporting our drug discovery programmes.",
    "We are a CDMO partnering with biopharma companies worldwide.",
    "Novo Nordisk is a leading global pharmaceutical company.",
    "Support preclinical oncology studies and IND-enabling work.",
    "Our gene therapy platform targets rare diseases.",
    "Experience with bioprocessing and Good Manufacturing Practice is required.",
]
OTHER_TEXTS = [
    "We build payroll software for small businesses.",
    "Our consultancy serves clients in retail, energy and pharma.",  # one passing mention
    "Oncology ward nurse, NHS hospital, night shifts.",
    "Data engineer: Spark, Airflow, dbt. Visit gmp.example.com.",
    "Indeed we are hiring an IND-ustrial designer.",  # case-sensitive acronyms
    "Sales role in life sciences.",
]


@pytest.mark.parametrize("text", BIOTECH_TEXTS)
def test_biotech_texts(text):
    assert detect_industry(text)[0] == BIOTECH


@pytest.mark.parametrize("text", OTHER_TEXTS)
def test_other_texts(text):
    assert detect_industry(text) == (None, [])


def test_label_carries_industry_and_evidence():
    label = RulesClassifier().classify("Filler. " * 30 + "We are a clinical-stage biotech company. " + "More. " * 30)
    assert label.industry == BIOTECH
    assert label.industry_evidence and all(len(e) <= 160 for e in label.industry_evidence)
    assert RulesClassifier().classify("We sell shoes.").industry is None


def test_biotech_naics_codes():
    assert biotech_naics("325414") and biotech_naics("3254") and biotech_naics("541714") and biotech_naics("541711")
    assert not biotech_naics("541511") and not biotech_naics(None) and not biotech_naics("")
