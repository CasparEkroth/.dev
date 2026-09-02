import tempfile
import unittest
from pathlib import Path

from scripts.amon.tools.skills import RESOURCE_LIST_CAP, load_skill


class TestLoadSkill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill_dir = Path(self.tmp.name) / "my-skill"
        self.skill_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_skill_md(self, body: str = "Do the thing.") -> None:
        (self.skill_dir / "SKILL.md").write_text(
            f"---\nname: my-skill\ndescription: does things\n---\n{body}\n"
        )

    def test_returns_skill_md_content(self):
        self._write_skill_md("Follow these steps.")
        result = load_skill(self.skill_dir)
        self.assertIn("Follow these steps.", result)

    def test_lists_resource_files(self):
        self._write_skill_md()
        (self.skill_dir / "helper.py").write_text("x = 1")
        result = load_skill(self.skill_dir)
        self.assertIn("helper.py", result)

    def test_excludes_pycache_and_git_dirs(self):
        self._write_skill_md()
        pycache = self.skill_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "helper.cpython-314.pyc").write_bytes(b"junk")
        gitdir = self.skill_dir / ".git"
        gitdir.mkdir()
        (gitdir / "config").write_text("junk")

        result = load_skill(self.skill_dir)
        self.assertNotIn("helper.cpython-314.pyc", result)
        self.assertNotIn(".git", result.replace("resources:\n", ""))

    def test_caps_resource_count_with_truncation_note(self):
        self._write_skill_md()
        for i in range(RESOURCE_LIST_CAP + 10):
            (self.skill_dir / f"file_{i:04d}.txt").write_text("x")

        result = load_skill(self.skill_dir)
        listed = [
            line
            for line in result.splitlines()
            if line.startswith("file_") or "file_" in line
        ]
        shown = [line for line in listed if line.endswith(".txt")]
        self.assertEqual(len(shown), RESOURCE_LIST_CAP)
        self.assertIn(f"and 10 more not shown (capped at {RESOURCE_LIST_CAP})", result)

    def test_under_cap_has_no_truncation_note(self):
        self._write_skill_md()
        (self.skill_dir / "a.txt").write_text("x")
        result = load_skill(self.skill_dir)
        self.assertNotIn("more not shown", result)


if __name__ == "__main__":
    unittest.main()
