import pytest

from sponsorscope.classify.level import detect_level


@pytest.mark.parametrize("title, category, expected", [
    ("PhD Studentship: Dynamic Performance and AI-Driven Optimisation", None, "phd"),
    ("Fully Funded Doctoral Landscape Award: Creative & Caring Communities", None, "phd"),
    ("Marie Sklodowska-Curie Actions Doctoral Network BlueOcean (3522426DA)", None, "phd"),
    ("Self-Funded PhD/MPhil Research Degree- May 2027", None, "phd"),
    ("Doctoral Candidate in Marine Biology", None, "phd"),
    ("Promovendus Computational Linguistics", None, "phd"),
    ("Midlands Training Partnership projects", "Research Degree Studentships", "phd"),
    ("Master Thesis Student - Battery Modelling", None, "masters"),
    ("Masterarbeit im Bereich Leistungselektronik", None, "masters"),
    ("Graduation internship: optics design", None, "masters"),
    ("Funded MRes in Data Science", None, "masters"),
    # not degree offers
    ("Postdoctoral Research Associate - Membrane Protein Folding", None, None),
    ("Post-Doctoral Researcher in Wind Assisted Ship Propulsion", None, None),
    ("Doctoral Training Programmes Manager (0926-324)", None, None),
    ("Doctoral Training and Development Officer", None, None),
    ("PhD Data Scientist, Intern", None, None),
    ("Senior Data Scientist (PhD preferred)", None, None),
    ("CURRENT HARPER ADAMS STAFF ONLY: Part-time PhD", None, None),
    ("Scrum Master", None, None),
    ("Master Data Analyst", None, None),
    ("Project 4: soil carbon under cover crops", "Studentships", "phd"),
    ("Backend Engineer", "Engineering", None),
    ("Doktorand i datavetenskap", None, "phd"),
    ("MSc Thesis: reinforcement learning for grid control", None, "masters"),
    ("Afstudeeropdracht WO: digital twin", None, "masters"),
    ("Master student afstudeerstage AI", None, "masters"),
    ("Postdoktor i kemi med inriktning mot organisk kemi", None, None),
    ("Postdoktorand i molekylärbiologi", None, None),
    ("Assistant Editor (PhD Graduates)", None, None),
    ("Assistant Editor (Master's/PhD holder) - Healthcare", None, None),
    ("Afstudeerstage marketing", None, None),
    ("Kieferorthopäde / Zahnarzt M.Sc. Kieferorthopädie (m/w/d)", None, None),
])
def test_detect_level(title, category, expected):
    assert detect_level(title, category) == expected
