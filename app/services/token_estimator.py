"""Language-aware token count approximation.

Ported from Tencent/WeKnora (MIT License) — `internal/infrastructure/chunker/
tokens.go`. Adapted from Go to Python pure functions; semantics 1:1 with the
upstream implementation.

Reference: https://github.com/Tencent/WeKnora
License: MIT (Tencent), 2025

Why approximation instead of tiktoken: per-language chars-per-token ratios
are conservative (over-estimate), small (no model dependency), and good
enough for "fits inside the embedder's window" decisions. A precise tokenizer
would add a heavy dependency for marginal accuracy on a budget that already
carries a 0.9 safety factor.

Design:
- Per-language chars/token ratios (en=4.0, de=4.5, zh=1.7, mixed=3.0) tuned
  to slightly over-shoot real token counts so chunks stay under model limits.
- Detection is cheap CJK-vs-Latin counting + a tiny German stop-word probe.
  NOT a substitute for proper language identification — heuristic dispatch only.
- chars_for_token_limit applies a 0.9 safety factor (under-shoots model limits
  rather than overshooting).
"""

from __future__ import annotations

LANG_ENGLISH = "en"
LANG_GERMAN = "de"
LANG_CHINESE = "zh"
LANG_MIXED = "mixed"

# Per-language chars/token ratios. Conservative — err toward over-estimating
# token counts so estimates don't underflow the real model usage.
_CHARS_PER_TOKEN: dict[str, float] = {
    LANG_ENGLISH: 4.0,
    LANG_GERMAN: 4.5,
    LANG_CHINESE: 1.7,
    LANG_MIXED: 3.0,
}

# Safety factor applied to chars_for_token_limit so we under-shoot the model
# limit. Matches WeKnora's `0.9` constant in `CharsForTokenLimit`.
_SAFETY_FACTOR = 0.9

# CJK script blocks used in language detection. We treat Han, Hangul, Hiragana,
# and Katakana all as "CJK" for the chars/token ratio purposes since their
# embedding tokenizations behave similarly (1-2 chars/token).
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs (Han)
    (0x3400, 0x4DBF),   # CJK Unified Ideographs Extension A
    (0x20000, 0x2A6DF), # CJK Unified Ideographs Extension B
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0xAC00, 0xD7AF),   # Hangul Syllables
    (0x1100, 0x11FF),   # Hangul Jamo
)

_GERMAN_UMLAUTS = frozenset("äöüÄÖÜß")
_GERMAN_STOPWORDS = (
    " der ", " die ", " das ", " und ", " ist ", " nicht ", " mit ", " auf ",
)


def _is_cjk(codepoint: int) -> bool:
    for lo, hi in _CJK_RANGES:
        if lo <= codepoint <= hi:
            return True
    return False


def _has_german_words(text: str) -> bool:
    """Cheap stop-word probe over the first 512 chars; lower-cased compare.

    False positives on borrowed terms are acceptable — this is a heuristic.
    """
    sample = text[:512].lower()
    return any(stop in sample for stop in _GERMAN_STOPWORDS)


def detect_language(text: str) -> str:
    """Coarse language label by counting CJK runes vs Latin runes.

    Returns one of LANG_CHINESE / LANG_GERMAN / LANG_ENGLISH / LANG_MIXED.
    Empty input → LANG_MIXED. Heuristic dispatch only, not real language ID.
    """
    if not text:
        return LANG_MIXED

    cjk = 0
    latin = 0
    umlaut = 0
    for ch in text:
        cp = ord(ch)
        if _is_cjk(cp):
            cjk += 1
        elif ch in _GERMAN_UMLAUTS:
            umlaut += 1
            latin += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin += 1

    total = cjk + latin
    if total == 0:
        return LANG_MIXED

    cjk_ratio = cjk / total
    latin_ratio = latin / total
    # Mixed: meaningful presence of both scripts (>=15% each).
    if cjk_ratio >= 0.15 and latin_ratio >= 0.15:
        return LANG_MIXED
    if cjk_ratio > 0.3:
        return LANG_CHINESE
    if umlaut > 0 or _has_german_words(text):
        return LANG_GERMAN
    return LANG_ENGLISH


def approx_token_count(text: str, lang: str) -> int:
    """Conservative token estimate for `text` in `lang`.

    Empty/None text returns 0. Unknown lang falls back to LANG_MIXED ratio.
    Result is at least 1 for any non-empty text (matches WeKnora behavior).
    """
    if not text:
        return 0
    rune_len = len(text)  # Python str length is codepoint count, equivalent to Go RuneCountInString
    return _approx_token_count_from_rune_len(rune_len, lang)


def _approx_token_count_from_rune_len(rune_len: int, lang: str) -> int:
    if rune_len <= 0:
        return 0
    ratio = _CHARS_PER_TOKEN.get(lang, _CHARS_PER_TOKEN[LANG_MIXED])
    approx = rune_len / ratio
    if approx < 1:
        return 1
    return int(approx + 0.5)


def chars_for_token_limit(tokens: int, lang: str) -> int:
    """Convert a token budget to an approximate character budget for `lang`.

    Applies a 0.9 safety factor so we under-shoot the model's hard limit
    rather than overshooting (matches WeKnora's CharsForTokenLimit).
    Returns 0 for tokens <= 0.
    """
    if tokens <= 0:
        return 0
    ratio = _CHARS_PER_TOKEN.get(lang, _CHARS_PER_TOKEN[LANG_MIXED])
    return int(tokens * ratio * _SAFETY_FACTOR)


__all__ = [
    "LANG_ENGLISH",
    "LANG_GERMAN",
    "LANG_CHINESE",
    "LANG_MIXED",
    "approx_token_count",
    "detect_language",
    "chars_for_token_limit",
]
