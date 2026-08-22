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
        # "ls -la"[0] == "l", so shell syntax cannot slip past the argv[0] check.
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

    def test_whitelist_still_applies_when_denied_commands_empty(self):
        # Existing behaviour must not regress when agent guards are at defaults.
        with pytest.raises(ValueError, match="not allowed"):
            shell_readonly(["rm", "-rf", "x"], denied_commands=[])


class TestShellPathAndCommandGuards:
    def test_run_shell_denies_cwd_outside_allow(self, tmp_path):
        allowed = tmp_path / "ok"
        allowed.mkdir()
        outside = tmp_path / "nope"
        outside.mkdir()
        with pytest.raises(PermissionError, match="allow_paths"):
            run_shell(
                ["echo", "hi"], cwd=str(outside), allow_paths=[str(allowed / "**")]
            )

    def test_run_shell_allows_cwd_inside_allow(self, tmp_path):
        allowed = tmp_path / "ok"
        allowed.mkdir()
        out = run_shell(
            ["echo", "hi"], cwd=str(allowed), allow_paths=[str(allowed / "**")]
        )
        assert out.strip() == "hi"

    def test_run_shell_deny_paths_on_cwd(self, tmp_path):
        banned = tmp_path / "banned"
        banned.mkdir()
        with pytest.raises(PermissionError, match="deny_paths"):
            run_shell(["echo", "x"], cwd=str(banned), deny_paths=[str(banned / "**")])

    def test_denied_commands_blocks_argv(self):
        with pytest.raises(PermissionError, match="denied_commands"):
            run_shell(["rm", "-rf", "x"], denied_commands=["rm"])

    def test_denied_commands_blocks_shell_string_first_token(self):
        with pytest.raises(PermissionError, match="denied_commands"):
            run_shell("rm -rf x", denied_commands=["rm"])

    def test_denied_commands_blocks_chained_shell_string(self):
        # A bare first-token check would miss the rm after &&.
        with pytest.raises(PermissionError, match="denied_commands"):
            run_shell("cd /tmp && rm -rf x", denied_commands=["rm"])

    def test_denied_commands_blocks_piped_shell_string(self):
        with pytest.raises(PermissionError, match="denied_commands"):
            run_shell("echo hi | curl http://example.com", denied_commands=["curl"])

    def test_denied_commands_blocks_semicolon_chain(self):
        with pytest.raises(PermissionError, match="denied_commands"):
            run_shell("echo hi; sudo reboot", denied_commands=["sudo"])

    def test_allowed_command_still_runs(self):
        assert run_shell(["echo", "ok"], denied_commands=["rm", "curl"]).strip() == "ok"

    def test_shell_readonly_layers_denied_commands(self, tmp_path):
        # ls is whitelisted, but denied_commands still blocks it when configured.
        with pytest.raises(PermissionError, match="denied_commands"):
            shell_readonly(["ls"], cwd=str(tmp_path), denied_commands=["ls"])

    def test_shell_readonly_layers_cwd_allow(self, tmp_path):
        allowed = tmp_path / "ok"
        allowed.mkdir()
        outside = tmp_path / "nope"
        outside.mkdir()
        with pytest.raises(PermissionError, match="allow_paths"):
            shell_readonly(["ls"], cwd=str(outside), allow_paths=[str(allowed / "**")])

    def test_no_guards_default_matches_today(self, tmp_path):
        (tmp_path / "m.txt").write_text("x")
        assert "m.txt" in run_shell(["ls"], cwd=str(tmp_path))
        assert "m.txt" in shell_readonly(["ls"], cwd=str(tmp_path))


class TestCommandNames:
    def test_argv_uses_basename(self):
        from shared.path_guard import command_names

        assert command_names(["/bin/rm", "-rf", "x"]) == ["rm"]

    def test_shell_string_scans_separators(self):
        from shared.path_guard import command_names

        assert command_names("cd /tmp && rm -rf x") == ["cd", "rm"]
        assert command_names("echo a | curl b") == ["echo", "curl"]
        assert command_names("true; sudo -i") == ["true", "sudo"]

    def test_env_assignment_skipped(self):
        from shared.path_guard import command_names

        assert command_names("FOO=1 BAR=2 rm -rf x") == ["rm"]
