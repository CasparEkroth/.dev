import tempfile
import unittest
from pathlib import Path

from scripts.amon.tools.todo import get_todos, render_todos, write_todos


class TestWriteTodosPersisted(unittest.TestCase):
    """session_id given -> persisted to disk via scripts.amon.memory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, todos, session_id="s1"):
        return write_todos(todos, session_id=session_id, session_dir=self.session_dir)

    def _read(self, session_id="s1"):
        return get_todos(session_id, session_dir=self.session_dir)

    def test_write_and_read_back(self):
        self._write([{"content": "step one", "status": "pending"}])
        self.assertEqual(self._read(), [{"content": "step one", "status": "pending"}])

    def test_empty_list_clears(self):
        self._write([{"content": "a", "status": "pending"}])
        self._write([])
        self.assertEqual(self._read(), [])

    def test_status_transitions_persist(self):
        self._write([{"content": "a", "status": "pending"}])
        self._write([{"content": "a", "status": "in_progress"}])
        self._write([{"content": "a", "status": "completed"}])
        self.assertEqual(self._read(), [{"content": "a", "status": "completed"}])

    def test_invalid_status_is_dropped_not_raised(self):
        result = self._write([{"content": "a", "status": "done"}])
        self.assertEqual(self._read(), [])
        self.assertIn("invalid status", result)

    def test_missing_content_is_dropped_not_raised(self):
        result = self._write([{"status": "pending"}])
        self.assertEqual(self._read(), [])
        self.assertIn("missing 'content'", result)

    def test_multiple_in_progress_allowed_with_note(self):
        result = self._write(
            [
                {"content": "a", "status": "in_progress"},
                {"content": "b", "status": "in_progress"},
            ]
        )
        self.assertEqual(len(self._read()), 2)
        self.assertIn("2 items are 'in_progress'", result)

    def test_sessions_are_isolated(self):
        self._write([{"content": "only in a", "status": "pending"}], session_id="a")
        self._write([{"content": "only in b", "status": "pending"}], session_id="b")
        self.assertEqual(
            self._read("a"), [{"content": "only in a", "status": "pending"}]
        )
        self.assertEqual(
            self._read("b"), [{"content": "only in b", "status": "pending"}]
        )

    def test_rendered_output_contains_content_and_status(self):
        result = self._write([{"content": "write tests", "status": "in_progress"}])
        self.assertIn("write tests", result)
        self.assertIn("in_progress", result)

    def test_survives_a_fresh_read_like_a_resumed_process(self):
        # No shared in-memory state involved: writing then reading via two
        # independent calls is what a resumed / spawned process actually does.
        self._write([{"content": "a", "status": "completed"}])
        self.assertEqual(
            get_todos("s1", session_dir=self.session_dir),
            [{"content": "a", "status": "completed"}],
        )


class TestWriteTodosEphemeral(unittest.TestCase):
    """No session_id -> in-memory fallback, not written to disk."""

    def test_write_and_read_back(self):
        write_todos([{"content": "x", "status": "pending"}], session_id=None)
        self.assertEqual(get_todos(None), [{"content": "x", "status": "pending"}])

    def test_no_session_dir_side_effect(self):
        with tempfile.TemporaryDirectory() as d:
            session_dir = Path(d)
            write_todos(
                [{"content": "x", "status": "pending"}],
                session_id=None,
                session_dir=session_dir,
            )
            self.assertEqual(list(session_dir.iterdir()), [])


class TestRenderTodos(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(render_todos([]), "Todo list is empty.")

    def test_renders_each_item_on_its_own_line(self):
        rendered = render_todos(
            [
                {"content": "a", "status": "completed"},
                {"content": "b", "status": "pending"},
            ]
        )
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("a", lines[0])
        self.assertIn("b", lines[1])


if __name__ == "__main__":
    unittest.main()
