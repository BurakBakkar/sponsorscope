from __future__ import annotations

import re

from sponsorscope.classify.industry import detect_industry
from sponsorscope.models import Label

VERSION = "rules-3"  # bump whenever rules change: the next run re-labels every posting
EVIDENCE_WIDTH = 160
NEGATION_WINDOW = 30

_F = re.IGNORECASE

NO_RULES = {
    "unable_to_offer": r"\b(?:unable|not able) to (?:offer|provide|support) (?:any )?(?:visa |work permit )?sponsorship\b",
    "not_offer": r"\b(?:does not|doesn't|do not|don't|will not|won't|can't|cannot|can not) (?:offer|provide|support) (?:visa |work permit )?sponsorship\b",
    "no_sponsorship": r"\bno (?:relocation (?:or|and|/) )?(?:visa |work permit )?sponsorship\b",
    "right_to_work": r"\bmust (?:already )?(?:have|hold) (?:the |an existing |existing |full |the full )?right to work\b",
    "not_available": r"\b(?:visa )?sponsorship (?:is |will )?not (?:be )?(?:available|offered|provided|possible)\b",
    "cannot_sponsor": r"\b(?:cannot|can ?not|can't|do not|don't|does not|doesn't|will not|won't|unable to|not (?:currently )?able to|won't be able to|will not be able to)(?: currently)? sponsor\b",
    "not_offering": r"\b(?:not|aren't|isn't) (?:currently )?(?:offering|providing) (?:visa |work permit )?sponsorship\b",
    "unavailable": r"\b(?:visa )?sponsorship (?:is |will be )?unavailable\b",
    "not_require": r"\b(?:not|never) (?:now or in the future )?(?:require|need) (?:visa |employer |immigration )?sponsorship\b",
    "without_sponsorship": r"\bwithout (?:the need for |requiring |needing )?(?:visa |employer )?sponsorship\b",
    "not_eligible": r"\bnot eligible for (?:visa |work permit )?sponsorship\b",
    "not_in_position": r"\bnot (?:currently )?in a position to (?:offer|provide) (?:visa )?sponsorship\b",
}
YES_RULES = {
    "sponsorship_available": r"\b(?:visa )?sponsorship (?:is )?(?:available|offered|provided)\b",
    "we_sponsor": r"\bwe (?:can|will|are able to|do|happily|gladly) sponsor\b",
    "offer_sponsorship": r"\b(?:offer|offers|offering|provide|provides|providing|include|includes|including) (?:full )?(?:visa |work permit )sponsorship\b",
    "relocation_visa": r"\b(?:relocation and visa|visa and relocation) (?:support|assistance|package)\b",
    "highly_skilled_migrant": r"\bhighly skilled migrant\b",
    "kennismigrant": r"\bkennismigrant\b",
    "open_to_sponsor": r"\bopen to sponsoring\b",
    "sponsor_visa": r"\bsponsor (?:your |a |the )?(?:work )?(?:visa|work permit|skilled worker visa)\b",
}
_NO = [re.compile(p, _F) for p in NO_RULES.values()]
_YES = [re.compile(p, _F) for p in YES_RULES.values()]
_NEGATION = re.compile(r"\b(?:not|no|unable|cannot|can't|won't|don't|never)\b", _F)

LANGUAGES = {
    "nl": "dutch", "de": "german", "fr": "french", "da": "danish", "fi": "finnish",
    "sv": "swedish", "no": "norwegian", "es": "spanish", "it": "italian", "pt": "portuguese",
    "pl": "polish", "ja": "japanese", "zh": "mandarin|chinese",
}
_LEVEL = r"(?:fluent|fluency|native|proficient|proficiency|c1|c2|b2)"
_LANG_PATTERNS = {
    code: [
        re.compile(rf"\b{_LEVEL}\b[\w \-]{{0,30}}?\b(?:{names})\b", _F),
        re.compile(rf"\b(?:{names})(?: language)?(?: skills)?(?: is| are)? (?:required|essential|a must|mandatory)\b", _F),
        re.compile(rf"\b(?:{names})\s*\(?(?:c1|c2|b2|native|fluent)\b", _F),
    ]
    for code, names in LANGUAGES.items()
}
_OPTIONAL = re.compile(r"\b(?:plus|nice to have|advantage|bonus|preferred|desirable|beneficial)\b", _F)
_CLAUSE_BREAK = re.compile(r"[.!?;,\n]")
_SENTENCE_BREAK = re.compile(r"[.!?;\n]")


def _prepare(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _context(text: str, start: int, end: int) -> str:
    pad = max(0, (EVIDENCE_WIDTH - (end - start)) // 2)
    return text[max(0, start - pad):min(len(text), end + pad)].strip()[:EVIDENCE_WIDTH]


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - NEGATION_WINDOW):start]
    breaks = list(_SENTENCE_BREAK.finditer(window))
    if breaks:
        window = window[breaks[-1].end():]
    return _NEGATION.search(window) is not None


def _clause(text: str, start: int, end: int) -> str:
    before = list(_CLAUSE_BREAK.finditer(text, 0, start))
    after = _CLAUSE_BREAK.search(text, end)
    return text[before[-1].end() if before else 0:after.start() if after else len(text)]


class RulesClassifier:
    """Deterministic phrase rules. Conflicting signals → unknown + mixed (see spec §7)."""

    version = VERSION

    def classify(self, text: str) -> Label:
        text = _prepare(text)
        no_hits = [m for rx in _NO for m in rx.finditer(text)]
        yes_hits = [m for rx in _YES for m in rx.finditer(text) if not _negated(text, m.start())]
        if yes_hits and no_hits:
            sponsorship, mixed = "unknown", True
        elif no_hits:
            sponsorship, mixed = "no", False
        elif yes_hits:
            sponsorship, mixed = "yes", False
        else:
            sponsorship, mixed = "unknown", False
        evidence = list(dict.fromkeys(_context(text, m.start(), m.end()) for m in no_hits + yes_hits))
        langs = []
        for code, patterns in _LANG_PATTERNS.items():
            for rx in patterns:
                if any(not _OPTIONAL.search(_clause(text, m.start(), m.end())) for m in rx.finditer(text)):
                    langs.append(code)
                    break
        industry, industry_hits = detect_industry(text)
        return Label(sponsorship=sponsorship, mixed=mixed, languages_required=tuple(langs),
                     evidence=tuple(evidence), industry=industry,
                     industry_evidence=tuple(dict.fromkeys(_context(text, m.start(), m.end()) for m in industry_hits)))
