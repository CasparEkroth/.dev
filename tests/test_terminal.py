import unittest

from scripts.amon.terminal import (
    _TODO_LINE_RE,
    StatusFooter,
    footer,
    reset_context,
    update_footer,
)
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

    def test_angle_bracket_in_todo_text_does_not_crash_render(self):
        # Regression: prompt_toolkit's HTML() parses "<...>" as markup and
        # raised ExpatError on ordinary text like "List<int>" before this
        # was escaped via .format() instead of raw string concatenation.
        footer = StatusFooter()
        footer.set_todo_lines(["○ [pending] fix List<int> handling & done"])
        html = footer.render_html()  # must not raise
        self.assertIn("List&lt;int&gt;", str(html))
        self.assertIn("&amp;", str(html))

    def test_bold_markup_in_header_still_renders_as_markup(self):
        # The header's own <b> tags are real markup, not user text, and must
        # survive the same render_html() call that now escapes todo_lines.
        footer = StatusFooter()
        footer.set_todo_lines(["○ [pending] a"])
        self.assertIn("<b>", str(footer.render_html()))


class TestModuleFooterHelpers(unittest.TestCase):
    """update_footer/reset_context operate on the module-level `footer`
    singleton, so each test resets it to avoid leaking into others."""

    def tearDown(self):
        footer.reset_footer(token=True, context=True, todos=True)

    def test_update_footer_context_zero_actually_sets_zero(self):
        # Regression: `if context:` treated an explicit 0 the same as "not
        # provided," so context could never actually be set to 0. Callers
        # now signal "don't touch it" with the None default instead.
        footer.set_context(42)
        update_footer(context=0)
        self.assertEqual(footer.context_current, 0)

    def test_update_footer_no_context_arg_leaves_it_untouched(self):
        footer.set_context(42)
        update_footer(tokens_added=5)
        self.assertEqual(footer.context_current, 42)
        self.assertEqual(footer.tokens, 5)

    def test_reset_context_clears_context_and_todos_not_tokens(self):
        footer.add_tokens(10)
        footer.set_context(99)
        footer.set_todo_lines(["✓ [completed] a"])
        reset_context()
        self.assertEqual(footer.context_current, 0)
        self.assertEqual(footer.todo_lines, [])
        self.assertEqual(footer.tokens, 10)


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
