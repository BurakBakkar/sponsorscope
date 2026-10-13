from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

SHORT_NAME_MAX = 4
FUZZY_CUTOFF = 95

LEGAL_SUFFIXES = frozenset({
    "ltd", "limited", "plc", "llp", "lp", "bv", "nv", "gmbh", "ag", "inc", "llc", "corp",
    "corporation", "co", "company", "as", "aps", "oy", "oyj", "ab", "sa", "sarl", "srl", "pty",
})
QUALIFIERS = frozenset({
    "uk", "nederland", "netherlands", "europe", "international", "holding", "holdings",
    "group", "services",
})
_TRAILING = LEGAL_SUFFIXES | QUALIFIERS
_DOTTED = [("b.v.", "bv"), ("n.v.", "nv"), ("a/s", "as")]


def normalize(name: str) -> str:
    """Canonical form of a company name for matching register entries to ATS boards."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ")
    for dotted, plain in _DOTTED:
        s = s.replace(dotted, plain)
    tokens = re.sub(r"[^a-z0-9]+", " ", s).split()
    while tokens and tokens[-1] in _TRAILING:
        tokens.pop()
    return " ".join(tokens)


def compact(norm: str) -> str:
    return norm.replace(" ", "")


@dataclass
class SponsorIndex:
    by_norm: dict[str, list[int]]
    by_compact: dict[str, set[str]]
    norms: list[str]

    @classmethod
    def build(cls, rows: Iterable[tuple[int, str]]) -> SponsorIndex:
        by_norm: dict[str, list[int]] = {}
        for sponsor_id, norm in rows:
            if norm:
                by_norm.setdefault(norm, []).append(sponsor_id)
        by_compact: dict[str, set[str]] = {}
        for norm in by_norm:
            by_compact.setdefault(compact(norm), set()).add(norm)
        return cls(by_norm=by_norm, by_compact=by_compact, norms=list(by_norm))


def find_match(company_norm: str, index: SponsorIndex) -> tuple[str, str, float] | None:
    """Return (sponsor_norm, method, score) for an unambiguous match, else None."""
    if len(compact(company_norm)) <= SHORT_NAME_MAX:
        return None
    if company_norm in index.by_norm:
        return company_norm, "exact", 100.0
    candidates = set(index.by_compact.get(compact(company_norm), set()))
    for norm, _score, _idx in process.extract(
        company_norm, index.norms, scorer=fuzz.token_sort_ratio, score_cutoff=FUZZY_CUTOFF, limit=3
    ):
        candidates.add(norm)
    if len(candidates) != 1:
        return None
    norm = candidates.pop()
    return norm, "normalised", float(fuzz.token_sort_ratio(company_norm, norm))


@dataclass
class Overrides:
    force: set[tuple[str, str]] = field(default_factory=set)
    forbid: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> Overrides:
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}

        def pairs(key: str) -> set[tuple[str, str]]:
            return {(normalize(e["company"]), normalize(e["sponsor"])) for e in data.get(key) or []}

        return cls(force=pairs("match"), forbid=pairs("forbid"))
