"""Characterization tests for scripts.git_suggest pure helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.git_suggest import (
    MAX_DIFF_CHARS,
    build_prompt,
    suggest_commit_message,
    truncate_text,
)


class TestTruncateText(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(truncate_text("hello", 100, "diff"), "hello")

    def test_exact_limit_unchanged(self):
        text = "x" * 50
        self.assertEqual(truncate_text(text, 50, "diff"), text)

    def test_long_text_keeps_head_and_tail(self):
        text = "A" * 400 + "MID" + "B" * 400
        limit = 300
        out = truncate_text(text, limit, "diff")
        self.assertLess(len(out), len(text))
        self.assertTrue(out.startswith("A"))
        self.assertTrue(out.endswith("B"))
        self.assertIn("truncated", out)
        self.assertIn("diff", out)
        self.assertNotIn("MID", out)

    def test_omitted_count_is_positive(self):
        text = "0123456789" * 50
        out = truncate_text(text, 80, "status")
        self.assertIn("chars of status truncated", out)


class TestBuildPrompt(unittest.TestCase):
    def test_raises_when_no_staged_diff(self):
        with patch("scripts.git_suggest.git_command") as git:
            git.side_effect = [
                "On branch main",
                "",
                "",
            ]
            with self.assertRaises(RuntimeError) as ctx:
                build_prompt("/tmp")
            self.assertIn("No staged changes", str(ctx.exception))

    def test_includes_status_stat_and_diff(self):
        with patch("scripts.git_suggest.git_command") as git:
            git.side_effect = [
                "On branch main\nChanges to be committed:\n",
                " file.py | 2 ++\n",
                "diff --git a/file.py b/file.py\n+hello\n",
            ]
            prompt = build_prompt("/repo")
        self.assertIn("On branch main", prompt)
        self.assertIn("file.py | 2 ++", prompt)
        self.assertIn("+hello", prompt)
        self.assertIn('"title"', prompt)

    def test_truncates_oversized_diff(self):
        big = "x" * (MAX_DIFF_CHARS + 5000)
        with (
            patch("scripts.git_suggest.git_command") as git,
            patch("scripts.git_suggest.sys.stderr"),
        ):
            git.side_effect = ["status", "stat", big]
            prompt = build_prompt("/repo")
        self.assertIn("truncated", prompt)
        self.assertLess(len(prompt), len(big))


class TestSuggestCommitMessage(unittest.TestCase):
    def test_formats_title_and_description(self):
        with (
            patch("scripts.git_suggest.build_prompt", return_value="PROMPT"),
            patch(
                "scripts.git_suggest.call_llm",
                return_value='{"title": "Add feature", "description": "Why."}',
            ),
        ):
            msg = suggest_commit_message(cwd="/repo")
        self.assertEqual(msg, "Add feature\n\nWhy.")

    def test_title_only_when_description_empty(self):
        with (
            patch("scripts.git_suggest.build_prompt", return_value="PROMPT"),
            patch(
                "scripts.git_suggest.call_llm",
                return_value='{"title": "Fix bug", "description": ""}',
            ),
        ):
            msg = suggest_commit_message(cwd="/repo")
        self.assertEqual(msg, "Fix bug")

    def test_invalid_json_raises(self):
        with (
            patch("scripts.git_suggest.build_prompt", return_value="PROMPT"),
            patch("scripts.git_suggest.call_llm", return_value="not-json"),
        ):
            with self.assertRaises(ValueError) as ctx:
                suggest_commit_message(cwd="/repo")
            self.assertIn("valid JSON", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
