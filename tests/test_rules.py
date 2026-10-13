from collections import Counter
from pathlib import Path

import yaml

from sponsorscope.classify.rules import VERSION, RulesClassifier

CORPUS = yaml.safe_load((Path(__file__).parent / "fixtures" / "labels.yaml").read_text())
CLF = RulesClassifier()


def test_corpus_is_large_enough():
    assert len(CORPUS) >= 60


def test_each_case_mixed_flag_and_languages():
    failures = []
    for case in CORPUS:
        label = CLF.classify(case["text"])
        if label.mixed != case.get("mixed", False) or list(label.languages_required) != case.get("langs", []):
            failures.append((case["text"], label))
    assert failures == []


def test_precision_and_recall_thresholds():
    stats = {c: Counter() for c in ("yes", "no")}
    for case in CORPUS:
        predicted = CLF.classify(case["text"]).sponsorship
        for c in stats:
            if predicted == c and case["sponsorship"] == c:
                stats[c]["tp"] += 1
            elif predicted == c:
                stats[c]["fp"] += 1
            elif case["sponsorship"] == c:
                stats[c]["fn"] += 1

    def precision(c):
        s = stats[c]
        return s["tp"] / (s["tp"] + s["fp"]) if s["tp"] + s["fp"] else 1.0

    def recall(c):
        s = stats[c]
        return s["tp"] / (s["tp"] + s["fn"]) if s["tp"] + s["fn"] else 1.0

    assert precision("no") >= 0.98, stats
    assert precision("yes") >= 0.95, stats
    assert recall("no") >= 0.80, stats
    assert recall("yes") >= 0.80, stats


def test_evidence_is_recorded_and_bounded():
    label = CLF.classify("Great team. " * 20 + "Unfortunately we are unable to offer visa sponsorship. " + "Apply now. " * 20)
    assert label.sponsorship == "no"
    assert label.evidence and all(len(e) <= 160 for e in label.evidence)
    assert any("unable to offer visa sponsorship" in e for e in label.evidence)


def test_mixed_records_both_sides():
    label = CLF.classify("We can sponsor visas for senior engineers but are unable to sponsor for internships.")
    assert label.sponsorship == "unknown" and label.mixed
    # short texts give one de-duplicated context string, so check content, not count
    assert any("We can sponsor" in e for e in label.evidence)
    assert any("unable to sponsor" in e for e in label.evidence)


def test_version_constant():
    assert CLF.version == VERSION == "rules-1"
