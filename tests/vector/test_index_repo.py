import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.vector.code.adapter import Symbol
from scripts.vector.embeddings import VectorItem
import scripts.vector.code.index_code as indexer


class FakeAdapter:
    def __init__(self, symbols):
        self.symbols = symbols

    def extract_symbols(self, code: str):
        return self.symbols


class TestIndexRepo(unittest.TestCase):
    def test_index_repo_indexes_file_and_symbols(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            file = repo / "main.py"

            code = "def hello(name):\n" "    return f'Hello {name}'\n"

            file.write_text(code, encoding="utf8")

            symbol = Symbol(
                kind="function",
                name="hello",
                signature="def hello(name):",
                start=0,
                end=len(code.encode("utf8")),
                start_line=1,
                end_line=2,
            )

            added = []

            with (
                patch.object(indexer, "scan_folder", return_value=[file]),
                patch.object(indexer, "should_skip", return_value=False),
                patch.object(
                    indexer, "llm_summarize_file", return_value="file summary"
                ),
                patch.object(
                    indexer, "llm_summarize_symbol", return_value="symbol summary"
                ),
                patch.object(indexer, "add_vector", side_effect=added.append),
                patch.object(indexer, "SUFFIX_TO_LANG", {".py": "python"}),
                patch.object(
                    indexer, "get_adapter", return_value=FakeAdapter([symbol])
                ),
            ):
                indexer.index_repo(repo)

            self.assertEqual(len(added), 2)

            file_item = added[0]
            symbol_item = added[1]

            self.assertIsInstance(file_item, VectorItem)
            self.assertEqual(file_item.payload["kind"], "file")
            self.assertEqual(file_item.payload["path"], str(file))
            self.assertEqual(file_item.payload["language"], "python")
            self.assertIn("file summary", file_item.text)

            self.assertIsInstance(symbol_item, VectorItem)
            self.assertEqual(symbol_item.payload["kind"], "symbol")
            self.assertEqual(symbol_item.payload["path"], str(file))
            self.assertEqual(symbol_item.payload["language"], "python")
            self.assertEqual(symbol_item.payload["name"], "hello")
            self.assertEqual(symbol_item.payload["symbol_type"], "function")
            self.assertEqual(symbol_item.payload["start_line"], 1)
            self.assertEqual(symbol_item.payload["end_line"], 2)
            self.assertIn("symbol summary", symbol_item.text)
            self.assertIn("def hello(name):", symbol_item.text)

    def test_index_repo_indexes_chunks_when_no_symbols(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            file = repo / "config.py"

            code = "API_URL = 'https://example.com'\n" "TIMEOUT = 30\n"

            file.write_text(code, encoding="utf8")

            added = []

            with (
                patch.object(indexer, "scan_folder", return_value=[file]),
                patch.object(indexer, "should_skip", return_value=False),
                patch.object(
                    indexer, "llm_summarize_file", return_value="file summary"
                ),
                patch.object(indexer, "add_vector", side_effect=added.append),
                patch.object(indexer, "SUFFIX_TO_LANG", {".py": "python"}),
                patch.object(indexer, "get_adapter", return_value=FakeAdapter([])),
            ):
                indexer.index_repo(repo)

            self.assertEqual(len(added), 2)

            file_item = added[0]
            chunk_item = added[1]

            self.assertIsInstance(file_item, VectorItem)
            self.assertEqual(file_item.payload["kind"], "file")
            self.assertIn("file summary", file_item.text)

            self.assertIsInstance(chunk_item, VectorItem)
            self.assertEqual(chunk_item.payload["kind"], "chunk")
            self.assertEqual(chunk_item.payload["path"], str(file))
            self.assertEqual(chunk_item.payload["language"], "python")
            self.assertEqual(chunk_item.payload["start_line"], 1)
            self.assertEqual(chunk_item.payload["end_line"], 2)
            self.assertIn("API_URL", chunk_item.text)
            self.assertIn("TIMEOUT", chunk_item.text)

    def test_index_repo_skips_ignored_files(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            file = repo / "ignored.py"
            file.write_text("def ignored(): pass\n", encoding="utf8")

            added = []

            with (
                patch.object(indexer, "scan_folder", return_value=[file]),
                patch.object(indexer, "should_skip", return_value=True),
                patch.object(indexer, "add_vector", side_effect=added.append),
            ):
                indexer.index_repo(repo)

            self.assertEqual(added, [])

    def test_index_repo_skips_unsupported_suffix(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            file = repo / "notes.unknown"
            file.write_text("some text", encoding="utf8")

            added = []

            with (
                patch.object(indexer, "scan_folder", return_value=[file]),
                patch.object(indexer, "should_skip", return_value=False),
                patch.object(indexer, "add_vector", side_effect=added.append),
                patch.object(indexer, "SUFFIX_TO_LANG", {}),
            ):
                indexer.index_repo(repo)

            self.assertEqual(added, [])

    def test_split_into_logical_chunks_creates_overlapping_chunks(self):
        content = "\n".join(f"line {i}" for i in range(1, 11))

        chunks = indexer.split_into_logical_chunks(
            content,
            max_lines=4,
            overlap=1,
        )

        self.assertEqual(len(chunks), 3)

        self.assertEqual(chunks[0].start_line, 1)
        self.assertEqual(chunks[0].end_line, 4)
        self.assertIn("line 1", chunks[0].text)
        self.assertIn("line 4", chunks[0].text)

        self.assertEqual(chunks[1].start_line, 4)
        self.assertEqual(chunks[1].end_line, 7)
        self.assertIn("line 4", chunks[1].text)
        self.assertIn("line 7", chunks[1].text)

        self.assertEqual(chunks[2].start_line, 7)
        self.assertEqual(chunks[2].end_line, 10)
        self.assertIn("line 7", chunks[2].text)
        self.assertIn("line 10", chunks[2].text)


if __name__ == "__main__":
    unittest.main()
