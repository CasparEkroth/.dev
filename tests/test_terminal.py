import json
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scripts.amon.terminal import (
    _TODO_LINE_RE,
    StatusFooter,
    _render_spawn_agents_result,
    _session_allowed_tools,
    confirm_tool,
    footer,
    reset_context,
    stream_action,
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


class TestConfirmTool(unittest.TestCase):
    def tearDown(self):
        _session_allowed_tools.clear()

    def test_y_allows_with_no_reason(self):
        with patch("builtins.input", return_value="y"):
            allowed, reason = confirm_tool("shell", {"command": ["ls"]})
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_n_denies_with_no_reason_when_left_blank(self):
        with patch("builtins.input", side_effect=["n", ""]):
            allowed, reason = confirm_tool("shell", {"command": ["ls"]})
        self.assertFalse(allowed)
        self.assertIsNone(reason)

    def test_n_denies_with_typed_reason(self):
        with patch("builtins.input", side_effect=["n", "not safe right now"]):
            allowed, reason = confirm_tool("shell", {"command": ["rm", "-rf", "x"]})
        self.assertFalse(allowed)
        self.assertEqual(reason, "not safe right now")

    def test_a_allows_and_remembers_for_the_session(self):
        with patch("builtins.input", return_value="a") as mock_input:
            allowed, reason = confirm_tool("shell_readonly", {"command": ["ls"]})
        self.assertTrue(allowed)
        self.assertIn("shell_readonly", _session_allowed_tools)
        self.assertEqual(mock_input.call_count, 1)

        # Second call for the same tool skips the prompt entirely.
        with patch("builtins.input") as mock_input_2:
            allowed, reason = confirm_tool("shell_readonly", {"command": ["pwd"]})
        self.assertTrue(allowed)
        self.assertIsNone(reason)
        mock_input_2.assert_not_called()

    def test_allowlist_is_per_tool_name(self):
        with patch("builtins.input", return_value="a"):
            confirm_tool("shell_readonly", {"command": ["ls"]})
        with patch("builtins.input", return_value="n") as mock_input:
            allowed, _ = confirm_tool("write_file", {"content": []})
        self.assertFalse(allowed)
        mock_input.assert_called()

    def test_reset_context_clears_the_allowlist(self):
        _session_allowed_tools.add("shell")
        reset_context()
        self.assertEqual(_session_allowed_tools, set())


class TestRenderSpawnAgentsResult(unittest.TestCase):
    def test_valid_json_list_renders_a_table(self):
        payload = json.dumps(
            [
                {
                    "agent": "worker",
                    "ok": True,
                    "usage": {"total_tokens": 42},
                    "turns": 2,
                    "session_id": "abcd1234-5678",
                }
            ]
        )
        result = _render_spawn_agents_result(payload)
        self.assertIsInstance(result, Panel)
        self.assertIsInstance(result.renderable, Table)

    def test_invalid_json_falls_back_to_a_plain_panel(self):
        result = _render_spawn_agents_result("not json at all")
        self.assertIsInstance(result, Panel)
        self.assertIsInstance(result.renderable, str)

    def test_truncated_json_falls_back_gracefully(self):
        # A real tool result can be cut mid-JSON by truncate_tool_output.
        truncated = json.dumps([{"agent": "w", "ok": True}])[:10]
        result = _render_spawn_agents_result(truncated)
        self.assertIsInstance(result, Panel)
        self.assertIsInstance(result.renderable, str)

    def test_non_list_json_falls_back_to_a_plain_panel(self):
        result = _render_spawn_agents_result(json.dumps({"not": "a list"}))
        self.assertIsInstance(result, Panel)
        self.assertIsInstance(result.renderable, str)


class TestChildStderrEvent(unittest.TestCase):
    def test_agent_name_and_bracketed_line_content_both_render_literally(self):
        # Regression: an unescaped "[{agent}]" is real Rich markup, not
        # literal text — Rich silently swallowed the agent name entirely,
        # and would do the same to any "[in_progress]"-style text in a
        # forwarded line (the child could be running a todo_write agent).
        test_console = Console(record=True, width=200)
        stream_action(
            "child_stderr",
            {"agent": "planner", "line": "status: [in_progress] thing"},
            console=test_console,
        )
        text = test_console.export_text()
        self.assertIn("[planner]", text)
        self.assertIn("[in_progress]", text)


if __name__ == "__main__":
    unittest.main()
