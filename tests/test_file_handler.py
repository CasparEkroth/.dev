import unittest
import tempfile
from pathlib import Path
from shared.file_handler import (
    read_file,
    read_files,
    scan_folder,
    write_file,
)


class TestWriteFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_missing_file(self):
        target = self.root / "new.txt"
        result = write_file([{"path": str(target), "old": "", "new": "hello"}])
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), "hello")
        self.assertIn("created file", result)

    def test_creates_missing_parent_dirs(self):
        target = self.root / "a" / "b" / "c.dzn"
        write_file([{"path": str(target), "old": "", "new": "x = 1;"}])
        self.assertEqual(target.read_text(), "x = 1;")

    def test_missing_file_without_content_is_not_created(self):
        target = self.root / "empty.txt"
        result = write_file([{"path": str(target), "old": "", "new": ""}])
        self.assertFalse(target.exists())
        self.assertIn("file not found", result)

    def test_missing_path_key_reports_instead_of_raising(self):
        result = write_file([{"old": "", "new": "content"}])
        self.assertIn("missing 'path'", result)

    def test_appends_to_existing_file(self):
        target = self.root / "log.txt"
        target.write_text("first\n")
        result = write_file([{"path": str(target), "old": "", "new": "second\n"}])
        self.assertEqual(target.read_text(), "first\nsecond\n")
        self.assertIn("appended content", result)

    def test_replaces_first_occurrence(self):
        target = self.root / "code.py"
        target.write_text("a = 1\na = 1\n")
        result = write_file([{"path": str(target), "old": "a = 1", "new": "a = 2"}])
        self.assertEqual(target.read_text(), "a = 2\na = 1\n")
        self.assertIn("updated successfully", result)

    def test_reports_missing_search_text(self):
        target = self.root / "code.py"
        target.write_text("a = 1\n")
        result = write_file([{"path": str(target), "old": "nope", "new": "x"}])
        self.assertEqual(target.read_text(), "a = 1\n")
        self.assertIn("search text not found", result)

    def test_batch_reports_one_line_per_section(self):
        created = self.root / "one.txt"
        missing = self.root / "two.txt"
        result = write_file(
            [
                {"path": str(created), "old": "", "new": "data"},
                {"path": str(missing), "old": "x", "new": "y"},
            ]
        )
        self.assertEqual(len(result.splitlines()), 2)
        self.assertIn("created file", result)
        self.assertIn("file not found", result)


class TestScanFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, rel: str, content: str = "") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_returns_all_files(self):
        a = self._make("a.py")
        b = self._make("sub/b.txt")
        result = scan_folder(self.root)
        self.assertIn(a, result)
        self.assertIn(b, result)

    def test_excludes_dirs(self):
        kept = self._make("main.py")
        excluded = self._make("node_modules/dep.js")
        result = scan_folder(self.root, excluded_dirs={"node_modules"})
        self.assertIn(kept, result)
        self.assertNotIn(excluded, result)

    def test_filters_by_suffix(self):
        py_file = self._make("a.py")
        txt_file = self._make("b.txt")
        result = scan_folder(self.root, suffixes={".py"})
        self.assertIn(py_file, result)
        self.assertNotIn(txt_file, result)

    def test_suffix_with_or_without_dot(self):
        py_file = self._make("a.py")
        result_dot = scan_folder(self.root, suffixes={".py"})
        result_no_dot = scan_folder(self.root, suffixes={"py"})
        self.assertIn(py_file, result_dot)
        self.assertIn(py_file, result_no_dot)

    def test_empty_folder_returns_empty_list(self):
        result = scan_folder(self.root)
        self.assertEqual(result, [])

    def test_no_suffix_filter_includes_all(self):
        self._make("a.py")
        self._make("b.md")
        self._make("c.json")
        result = scan_folder(self.root, suffixes=None)
        self.assertEqual(len(result), 3)

    def test_returns_list(self):
        self._make("a.py")
        result = scan_folder(self.root)
        self.assertIsInstance(result, list)


class TestReadFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, name: str, content: str = "") -> Path:
        p = self.root / name
        p.write_text(content)
        return p

    def test_reads_file_content(self):
        p = self._make("hello.py", "print('hello')")
        result = read_files([p])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "print('hello')")

    def test_entry_has_required_keys(self):
        p = self._make("foo.txt", "bar")
        result = read_files([p])
        self.assertIn("file_name", result[0])
        self.assertIn("path", result[0])
        self.assertIn("content", result[0])

    def test_file_name_matches(self):
        p = self._make("my_file.txt", "data")
        result = read_files([p])
        self.assertEqual(result[0]["file_name"], "my_file.txt")

    def test_path_is_string(self):
        p = self._make("a.py", "x = 1")
        result = read_files([p])
        self.assertIsInstance(result[0]["path"], str)

    def test_skips_nonexistent_paths(self):
        missing = self.root / "does_not_exist.py"
        result = read_files([missing])
        self.assertEqual(result, [])

    def test_empty_list_returns_empty(self):
        result = read_files([])
        self.assertEqual(result, [])

    def test_reads_multiple_files(self):
        p1 = self._make("a.py", "a")
        p2 = self._make("b.py", "b")
        result = read_files([p1, p2])
        self.assertEqual(len(result), 2)
        contents = {r["file_name"]: r["content"] for r in result}
        self.assertEqual(contents["a.py"], "a")
        self.assertEqual(contents["b.py"], "b")

    def test_reads_empty_file(self):
        p = self._make("empty.txt", "")
        result = read_files([p])
        self.assertEqual(result[0]["content"], "")


class TestReadFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "sample.txt"
        self.path.write_text("line1\nline2\nline3\nline4\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_line_1_returns_every_line(self):
        result = read_file(str(self.path), start_line=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], ["line1", "line2", "line3", "line4"])

    def test_start_and_end_line_are_1_based_inclusive(self):
        result = read_file(str(self.path), start_line=2, end_line=3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], ["line2", "line3"])


if __name__ == "__main__":
    unittest.main()
