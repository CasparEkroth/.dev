"""Characterization tests for scripts.search.search helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from scripts.search import search as search_mod


class TestWebSearch(unittest.TestCase):
    def test_formats_tavily_results_as_text_chunks(self):
        fake_client = MagicMock()
        fake_client.search.return_value = {
            "results": [
                {
                    "title": "Doc A",
                    "url": "https://example.com/a",
                    "score": 0.9,
                    "content": "alpha",
                },
                {
                    "title": "Doc B",
                    "url": "https://example.com/b",
                    "score": 0.5,
                    "content": "beta",
                },
            ]
        }
        with patch.object(search_mod, "_get_tavily_client", return_value=fake_client):
            chunks = search_mod.web_search("query", max_results=3)

        self.assertIsInstance(chunks, list)
        self.assertEqual(len(chunks), 2)
        self.assertIn("Title: Doc A", chunks[0])
        self.assertIn("URL: https://example.com/a", chunks[0])
        self.assertIn("Score: 0.9", chunks[0])
        self.assertIn("Content: alpha", chunks[0])
        fake_client.search.assert_called_once_with(
            query="query",
            max_results=3,
            include_favicon=False,
            include_answer=False,
            include_raw_content=False,
        )

    def test_search_delegates_to_web_search(self):
        with patch.object(search_mod, "web_search", return_value=["chunk"]) as web:
            out = search_mod.search("what is X")
        web.assert_called_once_with(query="what is X")
        self.assertEqual(out, ["chunk"])


if __name__ == "__main__":
    unittest.main()
