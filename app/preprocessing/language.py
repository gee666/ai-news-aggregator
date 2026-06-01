"""Language detection with optional dependencies and a tiny English heuristic fallback."""
from __future__ import annotations

try:
    from langdetect import detect as _langdetect
except Exception:  # pragma: no cover
    _langdetect = None
try:
    import langid
except Exception:  # pragma: no cover
    langid = None  # type: ignore[assignment]

_EN_WORDS = {"the", "and", "of", "to", "in", "for", "on", "with", "is", "that", "by", "from"}


def is_configured() -> bool:
    return _langdetect is not None or langid is not None


def detect_language(text: str | None) -> str | None:
    sample = (text or "").strip()[:5000]
    if not sample:
        return None
    if _langdetect is not None:
        try:
            return _langdetect(sample)
        except Exception:
            pass
    if langid is not None:
        try:
            return langid.classify(sample)[0]
        except Exception:
            pass
    words = [w.strip(".,:;!?()[]{}\"'").lower() for w in sample.split()[:200]]
    if words and sum(1 for w in words if w in _EN_WORDS) / max(len(words), 1) > 0.03:
        return "en"
    return None


def is_english(text: str | None) -> bool:
    return detect_language(text) in {"en", None}
