from __future__ import annotations

from typing import Protocol

from sponsorscope.models import Label


class Classifier(Protocol):
    version: str

    def classify(self, text: str) -> Label: ...
