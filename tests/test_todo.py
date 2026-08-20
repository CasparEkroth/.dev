import unittest

from scripts.amon.tools.todo import get_todos, render_todos, write_todos


class TestWriteTodos(unittest.TestCase):
    def test_write_and_read_back(self):
        write_todos([{"content": "step one", "status": "pending"}], session_id="s1")
        self.assertEqual(
            get_todos("s1"), [{"content": "step one", "status": "pending"}]
        )

    def test_empty_list_clears(self):
        write_todos([{"content": "a", "status": "pending"}], session_id="s2")
        write_todos([], session_id="s2")
        self.assertEqual(get_todos("s2"), [])

    def test_status_transitions_persist(self):
        write_todos([{"content": "a", "status": "pending"}], session_id="s3")
        write_todos([{"content": "a", "status": "in_progress"}], session_id="s3")
        write_todos([{"content": "a", "status": "completed"}], session_id="s3")
        self.assertEqual(get_todos("s3"), [{"content": "a", "status": "completed"}])

    def test_invalid_status_is_dropped_not_raised(self):
        result = write_todos([{"content": "a", "status": "done"}], session_id="s4")
        self.assertEqual(get_todos("s4"), [])
        self.assertIn("invalid status", result)

    def test_missing_content_is_dropped_not_raised(self):
        result = write_todos([{"status": "pending"}], session_id="s5")
        self.assertEqual(get_todos("s5"), [])
        self.assertIn("missing 'content'", result)

    def test_multiple_in_progress_allowed_with_note(self):
        result = write_todos(
            [
                {"content": "a", "status": "in_progress"},
                {"content": "b", "status": "in_progress"},
            ],
            session_id="s6",
        )
        self.assertEqual(len(get_todos("s6")), 2)
        self.assertIn("2 items are 'in_progress'", result)

    def test_sessions_are_isolated(self):
        write_todos([{"content": "only in a", "status": "pending"}], session_id="a")
        write_todos([{"content": "only in b", "status": "pending"}], session_id="b")
        self.assertEqual(
            get_todos("a"), [{"content": "only in a", "status": "pending"}]
        )
        self.assertEqual(
            get_todos("b"), [{"content": "only in b", "status": "pending"}]
        )

    def test_none_session_id_uses_default_key(self):
        write_todos([{"content": "x", "status": "pending"}], session_id=None)
        self.assertEqual(get_todos(None), [{"content": "x", "status": "pending"}])
        self.assertEqual(get_todos("default"), [{"content": "x", "status": "pending"}])

    def test_rendered_output_contains_content_and_status(self):
        result = write_todos(
            [{"content": "write tests", "status": "in_progress"}], session_id="s7"
        )
        self.assertIn("write tests", result)
        self.assertIn("in_progress", result)


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
