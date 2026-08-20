import unittest

from scripts.amon.terminal import _TODO_LINE_RE, StatusFooter
from scripts.amon.tools.todo import write_todos


class TestStatusFooterTodos(unittest.TestCase):
    def test_no_todo_lines_by_default(self):
        footer = StatusFooter()
        html = str(footer.render_html())
        self.assertNotIn("pending", html)

    def test_set_todo_lines_appears_in_render(self):
        footer = StatusFooter()
        footer.set_todo_lines(["○ [pending] a", "◐ [in_progress] b"])
        html = str(footer.render_html())
        self.assertIn("○ [pending] a", html)
        self.assertIn("◐ [in_progress] b", html)

    def test_reset_footer_todos_flag_clears_only_todos(self):
        footer = StatusFooter()
        footer.add_tokens(5)
        footer.set_todo_lines(["✓ [completed] a"])
        footer.reset_footer(todos=True)
        self.assertEqual(footer.todo_lines, [])
        self.assertEqual(footer.tokens, 5)

    def test_reset_footer_without_todos_flag_keeps_them(self):
        footer = StatusFooter()
        footer.set_todo_lines(["✓ [completed] a"])
        footer.reset_footer(context=True)
        self.assertEqual(footer.todo_lines, ["✓ [completed] a"])


class TestTodoLineExtraction(unittest.TestCase):
    def test_matches_rendered_checklist_lines(self):
        for line in [
            "○ [pending] a",
            "◐ [in_progress] b",
            "✓ [completed] c",
        ]:
            self.assertTrue(_TODO_LINE_RE.match(line), line)

    def test_does_not_match_notes_or_prose(self):
        for line in [
            "note: 2 items are 'in_progress' — usually only one should be at a time.",
            "item 0 ('a'): invalid status 'done', must be one of [...], skipped",
            "Todo list is empty.",
        ]:
            self.assertFalse(_TODO_LINE_RE.match(line), line)

    def test_extracts_only_checklist_lines_from_real_tool_output(self):
        out = write_todos(
            [
                {"content": "a", "status": "bogus"},
                {"content": "b", "status": "pending"},
            ],
            session_id=None,
        )
        lines = [line for line in out.splitlines() if _TODO_LINE_RE.match(line)]
        self.assertEqual(lines, ["○ [pending] b"])


if __name__ == "__main__":
    unittest.main()
