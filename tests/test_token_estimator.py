"""Tests for app/services/token_estimator.

Layer 1: WeKnora upstream test cases reproduced 1:1 — `internal/infrastructure/
chunker/tokens_test.go`. Port-correctness lock for the language-aware token
estimation: any drift here means the Python implementation diverged from the
Go semantics.

Layer 2: Python-port-specific behavior (negative tokens, empty detection).
"""

import unittest

from app.services.token_estimator import (
    LANG_CHINESE,
    LANG_ENGLISH,
    LANG_GERMAN,
    LANG_MIXED,
    approx_token_count,
    chars_for_token_limit,
    detect_language,
)


class ApproxTokenCountTests(unittest.TestCase):
    """1:1 with WeKnora `TestApproxTokenCount_*`."""

    def test_english_approximates_4_chars_per_token(self):
        # WeKnora: "The quick brown fox jumps over the lazy dog." → 44 chars / 4 ≈ 11
        # Range gate: 9..13 (loose; conservative-rounding tolerance)
        got = approx_token_count(
            "The quick brown fox jumps over the lazy dog.", LANG_ENGLISH
        )
        self.assertGreaterEqual(got, 9)
        self.assertLessEqual(got, 13)

    def test_chinese_approximates_1p7_chars_per_token(self):
        # WeKnora: "这是一段中文测试内容用于检验分词估算" → 18 codepoints / 1.7 ≈ 10
        got = approx_token_count("这是一段中文测试内容用于检验分词估算", LANG_CHINESE)
        self.assertGreaterEqual(got, 9)
        self.assertLessEqual(got, 12)

    def test_empty_returns_zero(self):
        self.assertEqual(approx_token_count("", LANG_ENGLISH), 0)

    def test_unknown_lang_falls_back_to_mixed(self):
        # WeKnora: unknown lang should not return 0 / negative — falls back to mixed ratio
        self.assertGreater(approx_token_count("Hello world hello world", "xx"), 0)


class DetectLanguageTests(unittest.TestCase):
    """1:1 with WeKnora `TestDetectLanguage_*`."""

    def test_english(self):
        self.assertEqual(
            detect_language("The quick brown fox jumps over the lazy dog."),
            LANG_ENGLISH,
        )

    def test_german_by_umlauts(self):
        self.assertEqual(
            detect_language("Der schnelle braune Fuchs springt über den faulen Hund."),
            LANG_GERMAN,
        )

    def test_german_by_stopwords(self):
        # No umlauts, but plenty of German function words — should still detect German.
        self.assertEqual(
            detect_language("Das ist ein Test und nicht mit Umlauten."),
            LANG_GERMAN,
        )

    def test_chinese(self):
        self.assertEqual(detect_language("这是一段中文测试内容"), LANG_CHINESE)

    def test_mixed(self):
        self.assertEqual(
            detect_language("This 这是 mixed 测试 content with 多语言 inside"),
            LANG_MIXED,
        )

    def test_empty_returns_mixed(self):
        # Python-port edge: empty string defaults to mixed (matches WeKnora).
        self.assertEqual(detect_language(""), LANG_MIXED)


class CharsForTokenLimitTests(unittest.TestCase):
    """1:1 with WeKnora `TestCharsForTokenLimit_*`."""

    def test_applies_safety_margin_english(self):
        # WeKnora: 1000 EN tokens → 1000 * 4 * 0.9 = 3600 chars (range 3500..3700)
        got = chars_for_token_limit(1000, LANG_ENGLISH)
        self.assertGreaterEqual(got, 3500)
        self.assertLessEqual(got, 3700)

    def test_zero_tokens_returns_zero(self):
        self.assertEqual(chars_for_token_limit(0, LANG_ENGLISH), 0)

    def test_negative_tokens_returns_zero(self):
        # Python-port edge: defensive handling of negative inputs (WeKnora returns 0 on <=0).
        self.assertEqual(chars_for_token_limit(-5, LANG_ENGLISH), 0)

    def test_chinese_budget_is_smaller_than_english(self):
        # zh ratio 1.7 vs en ratio 4.0 — for the same token budget, zh has fewer chars.
        zh = chars_for_token_limit(1000, LANG_CHINESE)
        en = chars_for_token_limit(1000, LANG_ENGLISH)
        self.assertLess(zh, en)


if __name__ == "__main__":
    unittest.main()
