"""Spot PhD and master's offers (degree positions) among postings, from the title and feed category."""
from __future__ import annotations

import re

_PHD = re.compile(
    r"\bph\.?\s?d\b|\bdphil\b|studentship|research degree|promovend|doktorand"
    r"|doctoral (?:\w+ ){0,2}(?:candidate|researcher|student|position|network|award|fellow)",
    re.I,
)
_MASTERS = re.compile(
    r"\bmaster'?s? ?(?:thesis|student|studentship|project|internship|position)|masterarbeit|\bm\.?sc\b|\bmres\b"
    r"|afstudeer|graduation (?:internship|assignment|project)",
    re.I,
)
# Staff roles that merely mention doctoral programmes, postdocs, internal-only calls, and internships/jobs for
# people who already hold a PhD.
_NOT_AN_OFFER = re.compile(
    r"post-?\s?doc|manager|officer|administrator|coordinator|director|lecturer|professor"
    r"|\bintern\b|preferred|required|staff only",
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
