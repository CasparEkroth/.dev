# Reference: paths

## Runtime discovery roots

| Kind | Path |
|------|------|
| System agents | `/etc/.amon/agents/*.json` |
| User agents | `~/.amon/agents/*.json` |
| Project agents | `$CWD/.amon/agents/*.json` |
| User skills (conventional) | `~/.amon/skills/<name>/SKILL.md` |
| User hooks (conventional) | `~/.amon/hooks/*` |
| Project skills/hooks | any path referenced by config / `skill://` |

## Runtime data dirs (overridable)

| Kind | Config symbol | Env override | Default |
|------|---------------|--------------|---------|
| Sessions | `config.SESSIONS_DIR` | `AMON_SESSIONS_DIR` | `scripts/amon/config/sessions/` |
| Tool output spill | `config.TOOL_OUTPUT_DIR` | `AMON_TOOL_OUTPUT_DIR` | `scripts/amon/config/tool_output/` |

Set env vars **before** process start (defaults are bound at import time).

### Session artifacts (under `SESSIONS_DIR`)

| File | Purpose |
|------|---------|
| `{uuid}` | Transcript JSON (conversation turns) |
| `{uuid}.meta.json` | Token / context meta (`context_tokens`) |
| `{uuid}.todos.json` | Checklist from `todo_write` (optional sidecar) |

`.meta.json` and `.todos.json` are excluded from session listings.
`remove_session` / `--delete-session` deletes transcript + both sidecars.
Todo module: `scripts/amon/tools/todo.py`; persistence: `scripts/amon/memory.py`.

## Repo paths (this codebase)

| Kind | Path |
|------|------|
| CLI | `scripts/amon/amon_cli.py` |
| Agent loop | `scripts/amon/agent_loop.py` |
| Terminal / REPL UI | `scripts/amon/terminal.py` |
| Hooks runner | `scripts/amon/hooks.py` |
| Session / todo memory | `scripts/amon/memory.py` |
| Agent model | `scripts/amon/tools/agent.py` |
| Tool registry | `scripts/amon/tools/registry.py` |
| Todo checklist tool | `scripts/amon/tools/todo.py` |
| Skills loader | `scripts/amon/tools/skills.py` |
| Sessions dir | `scripts/amon/config/sessions/` (via `config.SESSIONS_DIR`) |
| Tool output dir | `scripts/amon/config/tool_output/` (via `config.TOOL_OUTPUT_DIR`) |
| Setup installer | `scripts/amon/config/setup/install` |
| Bundled skill source | `scripts/amon/config/setup/python-validate/` |
| Human docs | `docs/amon/` |
| amon-author skill source | `docs/amon/examples/skills/amon-author/` |

## Installer outputs

`scripts/amon/config/setup/install` creates/refreshes:

- `~/.amon/agents/default.json` (`todo_write` in `allowed_tools`)
- `~/.amon/agents/planner.json`
- `~/.amon/agents/dev.json` (`todo_write` in `allowed_tools`)
- `~/.amon/skills/python-validate/`
- `~/.amon/skills/amon-author/` (copied from `docs/amon/examples/skills/amon-author`)
- `~/.amon/hooks/log.sh`

## Docs examples

| Artifact | Path |
|----------|------|
| Minimal agent | `docs/amon/examples/minimal-agent.json` |
| Agent + hooks | `docs/amon/examples/agent-with-hooks.json` |
| Planner-like | `docs/amon/examples/readonly-planner.json` |
| Path-restricted | `docs/amon/examples/path-restricted-agent.json` |
| Bash hook | `docs/amon/examples/hooks/log.sh` |
| Python hook | `docs/amon/examples/hooks/log.py` |
| Skill template | `docs/amon/examples/skills/SKILL.template.md` |
| This skill | `docs/amon/examples/skills/amon-author/` |
