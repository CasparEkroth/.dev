"""Tests for the shell tools: argv vs shell strings, timeouts, partial output."""

import inspect

import pytest

from scripts.amon.tools.shell import run_shell, shell_readonly


class TestRunShell:
    def test_runs_argv_list(self):
        assert run_shell(["echo", "hello"]).strip() == "hello"

    def test_string_command_uses_the_shell(self):
        # A pipe only works when the command goes through a shell.
        assert run_shell("echo one two three | wc -w").strip() == "3"

    def test_string_command_can_redirect(self, tmp_path):
        target = tmp_path / "out.txt"
        run_shell(f"echo written > {target}")
        assert target.read_text().strip() == "written"

    def test_shell_flag_joins_a_list(self):
        assert run_shell(["echo", "a", "|", "wc", "-c"], shell=True).strip() == "2"

    def test_cwd_is_respected(self, tmp_path):
        (tmp_path / "marker.txt").write_text("x")
        assert "marker.txt" in run_shell(["ls"], cwd=str(tmp_path))

    def test_timeout_returns_partial_output_instead_of_raising(self):
        result = run_shell("echo early; sleep 5", timeout=1)
        assert "timed out after 1s" in result
        assert "early" in result

    def test_longer_timeout_lets_the_command_finish(self):
        assert run_shell("sleep 1; echo done", timeout=10).strip() == "done"

    def test_non_zero_exit_surfaces_output(self):
        result = run_shell("echo to-stderr >&2; exit 3")
        assert "exit 3" in result
        assert "to-stderr" in result

    def test_default_timeout_comes_from_config(self):
        from config import DEFAULT_SHELL_TIMEOUT

        default = inspect.signature(run_shell).parameters["timeout"].default
        assert default == DEFAULT_SHELL_TIMEOUT


class TestShellReadonly:
    def test_allows_whitelisted_command(self, tmp_path):
        (tmp_path / "marker.txt").write_text("x")
        assert "marker.txt" in shell_readonly(["ls"], cwd=str(tmp_path))

    def test_rejects_non_whitelisted_command(self):
        with pytest.raises(ValueError, match="not allowed"):
            shell_readonly(["rm", "-rf", "/"])

    def test_rejects_a_shell_string(self):
        # "ls -la"[0] == "l", which is not on the whitelist, so a string command
        # can never smuggle shell syntax past the argv[0] check.
        with pytest.raises(ValueError, match="not allowed"):
            shell_readonly("ls -la | rm -rf /")

    def test_rejects_empty_command(self):
        with pytest.raises(ValueError, match="Empty command"):
            shell_readonly([])

    def test_rejects_write_git_subcommand(self):
        with pytest.raises(ValueError, match="git subcommand"):
            shell_readonly(["git", "push"])

    def test_accepts_a_timeout(self):
        assert "timeout" in inspect.signature(shell_readonly).parameters

    def test_has_no_shell_escape_hatch(self):
        assert "shell" not in inspect.signature(shell_readonly).parameters
