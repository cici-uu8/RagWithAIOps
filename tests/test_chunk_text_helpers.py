"""Tests for chunk_text_helpers.build_search_text."""

import unittest

from app.services.chunk_text_helpers import build_search_text


class BuildSearchTextTests(unittest.TestCase):
    def test_no_heading_returns_content_unchanged(self):
        self.assertEqual(build_search_text(None, "正文"), "正文")
        self.assertEqual(build_search_text([], "正文"), "正文")

    def test_with_heading_path_prefixes_with_space_joined_headings(self):
        self.assertEqual(
            build_search_text(["第一章", "概述"], "正文段"),
            "第一章 概述\n正文段",
        )

    def test_skips_empty_segments_in_heading_path(self):
        self.assertEqual(
            build_search_text(["", "概述", ""], "正文段"),
            "概述\n正文段",
        )

    def test_heading_only_empty_strings_returns_content(self):
        self.assertEqual(build_search_text(["", ""], "正文"), "正文")

    def test_non_string_heading_segments_are_coerced(self):
        self.assertEqual(
            build_search_text(["第一章", 2], "正文"),
            "第一章 2\n正文",
        )

    def test_bare_string_heading_path_is_treated_as_single_segment(self):
        self.assertEqual(build_search_text("第一章", "正文"), "第一章\n正文")
        self.assertEqual(build_search_text("", "正文"), "正文")

    def test_none_heading_path_returns_content(self):
        self.assertEqual(build_search_text(None, "正文"), "正文")


if __name__ == "__main__":
    unittest.main()
