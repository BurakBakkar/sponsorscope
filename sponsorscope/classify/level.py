"""Spot PhD and master's offers (degree positions) among postings, from the title and feed category."""
from __future__ import annotations

import re

_PHD = re.compile(
    r"\bph\.?\s?d\b|\bdphil\b|studentship|research degree|promovend|doktorand"
    r"|doctoral (?:\w+ ){0,2}(?:candidate|researcher|student|position|network|award|fellow)",
    re.I,
)
# A degree name only counts next to an offer word: "M.Sc." alone is usually a qualification the hire holds.
_MASTERS = re.compile(
    r"\b(?:master'?s?|m\.?sc\.?) ?(?:thesis|student|studentship|project|internship|position|assignment)"
    r"|masterarbeit|\bmres\b|graduation (?:internship|assignment|project)"
    r"|afstudeer\w*.*\b(?:master|wo|msc)\b|\b(?:master|wo|msc)\b.*afstudeer",  # afstudeer- alone is often HBO
    re.I,
)
# Staff roles that merely mention doctoral programmes, postdocs (incl. Swedish postdoktor), internal-only calls,
# and jobs/internships for people who already hold the degree.
_NOT_AN_OFFER = re.compile(
    r"post-?\s?do[ck]|manager|officer|administrator|coordinator|director|lecturer|professor"
    r"|\bintern\b|preferred|required|staff only|holders?\b|graduates\b",
    re.I,
)


def detect_level(title: str, category: str | None = None) -> str | None:
    """"phd" | "masters" | None. A studentship/research-degree feed category counts as a PhD offer."""
    if _NOT_AN_OFFER.search(title):
        return None
    if _PHD.search(title) or (category and _PHD.search(category)):
        return "phd"
    if _MASTERS.search(title):
        return "masters"
    return None
