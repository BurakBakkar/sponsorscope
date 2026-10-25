"""Biotech / pharma industry from posting text: weighted phrases, so one passing mention is not enough."""
from __future__ import annotations

import re

BIOTECH = "biotech"
THRESHOLD = 2  # one company-identity phrase, or two supporting ones

_F = re.IGNORECASE
# Phrases that say what the company or the work is (2 points each).
STRONG = {
    "biotech_company": r"\bbiotech(?:nology)? (?:company|start-?up|firm|scale-?up)\b",
    "biopharma": r"\bbio-?pharma(?:ceutical)?s?\b",
    "pharma_company": r"\bpharmaceutical (?:company|companies|group|manufacturer)\b",
    "clinical_stage": r"\bclinical[- ]stage\b",
    "drug_discovery": r"\bdrug (?:discovery|development|candidates?|substance|product)\b",
    "therapeutics": r"\b(?:cell|gene|cell and gene|rna|antibody|radioligand) therap(?:y|ies|eutics)\b",
    "biologics": r"\bbiologics\b",
    "antibodies": r"\b(?:monoclonal|bispecific) antibod(?:y|ies)\b",
    "gmp": r"\b(?:(?-i:c?GMP)|good manufacturing practices?)\b",  # acronyms stay case-sensitive
    "cro_cdmo": r"\b(?:CDMO|contract (?:research|development and manufacturing) organi[sz]ation)\b",
    "bioprocess": r"\bbioprocess(?:ing)?\b",
}
# Domain vocabulary that also shows up in software, consulting or hospital ads (1 point each).
SUPPORTING = {
    "biotech": r"\bbiotech(?:nology)?\b",
    "pharma": r"\bpharma(?:ceutical)?s?\b",
    "life_sciences": r"\blife[- ]sciences?\b",
    "clinical_trials": r"\bclinical (?:trials?|development|operations)\b",
    "preclinical": r"\bpre-?clinical\b",
    "molecular": r"\b(?:CRISPR|(?-i:mRNA)|genomics|proteomics|oncology|immunology|assays?)\b",
    "regulatory": r"\b(?:(?-i:FDA|EMA|IND)|regulatory affairs)\b",
}
_STRONG = [re.compile(p, _F) for p in STRONG.values()]
_SUPPORTING = [re.compile(p, _F) for p in SUPPORTING.values()]


def _first_hits(patterns: list[re.Pattern], text: str) -> list[re.Match]:
    return [m for rx in patterns if (m := rx.search(text))]


def detect_industry(text: str) -> tuple[str | None, list[re.Match]]:
    """("biotech", the matches that scored) or (None, []). Each phrase counts once, however often it appears."""
    strong = _first_hits(_STRONG, text)
    covered = {(m.start(), m.end()) for m in strong}
    supporting = [m for m in _first_hits(_SUPPORTING, text)
                  if not any(s <= m.start() and m.end() <= e for s, e in covered)]  # "biopharma" is not also "pharma"
    if 2 * len(strong) + len(supporting) < THRESHOLD:
        return None, []
    return BIOTECH, strong + supporting


# US NAICS: pharmaceutical and medicine manufacturing, and R&D in biotechnology (2017+ and pre-2017 codes).
BIOTECH_NAICS = {"3254": "Pharmaceutical and medicine manufacturing", "541714": "R&D in biotechnology",
                 "541711": "R&D in biotechnology"}


def biotech_naics(code: str | None) -> str | None:
    """The industry name when a NAICS code is biotech / pharma, else None."""
    return next((name for prefix, name in BIOTECH_NAICS.items() if code and code.startswith(prefix)), None)
