from __future__ import annotations

from functools import lru_cache

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

MIN_RELIABLE_CHARS = 40
SHORT_TEXT_CHARS = 200  # below this lingua's confidence is low even for clear English
_LANGUAGES = [
    Language.ENGLISH, Language.DUTCH, Language.GERMAN, Language.FRENCH, Language.SPANISH,
    Language.PORTUGUESE, Language.ITALIAN, Language.DANISH, Language.SWEDISH, Language.FINNISH,
    Language.BOKMAL, Language.POLISH, Language.JAPANESE, Language.CHINESE,
]


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*_LANGUAGES).build()


def is_english(text: str, threshold: float = 0.8) -> bool:
    """True if the posting is English. Short text is kept unless another language wins: detection is unreliable there."""
    sample = text.strip()[:2000]
    if len(sample) < MIN_RELIABLE_CHARS:
        return True
    detector = _detector()
    if detector.compute_language_confidence(sample, Language.ENGLISH) >= threshold:
        return True
    if len(sample) < SHORT_TEXT_CHARS:
        # short text: only drop it when another language is the best guess
        return detector.detect_language_of(sample) in (Language.ENGLISH, None)
    return False
