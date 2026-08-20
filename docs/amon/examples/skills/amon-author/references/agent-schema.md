# Reference: agent JSON schema

Source model: `scripts/amon/tools/agent.py` → class `Agent`

## File locations

| Priority (low → high) | Glob |
|-----------------------|------|
| 1 system | `/etc/.amon/agents/*.json` |
| 2 user | `~/.amon/agents/*.json` |
| 3 project | `$CWD/.amon/agents/*.json` |

Map key = filename stem. Higher priority overwrites lower on conflict.

## Fields

| Field | Type | Required | Default | Constraints |
|-------|------|----------|---------|-------------|
| `name` | string | yes | — | — |
| `description` | string | yes | — | Shown in spawn_agents help |
| `system_prompt` | string | yes | — | Skills section appended at runtime |
| `tools` | string[] \| `"*"` | yes | — | Tool registry keys; `*` expands |
| `allowed_tools` | string[] \| `"*"` | yes | — | Confirmation bypass list; `*` expands |
| `allowed_skills` | string[] | no | `[]` | `skill://` URI patterns |
| `hooks` | object | no | `{}` | event → list of `{command, matcher?, timeout_ms?}`; a string or list of strings is normalized |
| `max_turns` | int | no | `DEFAULT_MAX_TURNS` (30) | must be `> 0` |
| `force_first_tool` | bool | no | `false` | Require a tool call on turn 0; off means the agent may open with a question |
| `max_runtime_s` | float | no | `null` | Wall-clock budget; the run stops between turns and keeps its partial result |
| `model` | string | no | `null` | Model id for this agent; falls back to `settings.LLM_MODEL`. Overridable per headless run via `--model` / job `model` |
| `system_prompt_template` | string | no | `null` | Overrides prompt assembly; placeholders `{prompt}`, `{workspace}`, `{skills}`. Double literal braces; unknown placeholders raise at run start |
| `max_tool_output_chars` | int | no | `null` | Per-agent ceiling for tool results before spill/truncate; `null` keeps global `MAX_TOOL_OUTPUT_CHARS` (20_000) |
| `mcp_servers` | object | no | `{}` | **STUB** — validated and ignored until MCP support lands |
| `allow_paths` | string[] | no | `[]` | Glob patterns; empty = unrestricted (unless denied). Matched after resolve |
| `deny_paths` | string[] | no | `[]` | Glob patterns; deny always wins over allow |
| `denied_commands` | string[] | no | `[]` | Command names blocked for `shell` / `shell_readonly` (command-position scan) |

### Path / command restriction notes

- Server-side only — bound via `functools.partial` in `get_registry`; **not** in
  tool schemas.
- Path rule: permitted iff not denied AND (allow empty OR allow-matched).
- `read_file` / `write_file`: hard path boundary.
- `shell` / `shell_readonly`: only `cwd` + command name(s). A permitted binary
  can still touch paths outside the allow tree — this is a guardrail, not a
  sandbox. See `docs/amon/agent-config.md`.

## `mcp_servers` (stub)

Accepted so configs written now keep working, but nothing is connected yet: the
servers are not started and their tools are not registered. Entry shapes follow
the usual conventions — local `{command, args, env, timeout, disabled,
disabledTools}`, remote `{url, headers, oauth, oauthScopes}`.

## `hooks` object keys

Exact strings (see hook events reference):

- `agentSpawn`
- `start`
- `stop`
- `preToolUse`
- `postToolUse`

## Known tool names

From `scripts/amon/tools/registry.py` (may grow):

- `shell`
- `shell_readonly`
- `read_file`
- `write_file`
- `load_skill`
- `todo_write`
- `spawn_agents` (registered after agents load)

### `todo_write` (tool args, not agent JSON)

- Args: `todos: [{content: string, status: "pending"|"in_progress"|"completed"}]`
- Full-list replace per call; result echoes the rendered checklist
- Session id bound server-side (not model-visible). With a session id, stored as
  `{session_id}.todos.json` under `SESSIONS_DIR` — survives `--resume`, cleaned
  by `remove_session`, shareable with `spawn_agents` children given the same id
- No session id → per-process in-memory fallback
- Confirmation follows `allowed_tools` like other tools

### `spawn_agents` job keys (tool args, not agent JSON)

Each job: `agent`, `task` (required); optional `save_session`, `session_id`,
`model`, `max_turns`. Top-level tool args: `max_parallel`, `timeout_s`, `output`
(checkpoint path). Same `session_id` shares the todo sidecar across processes.
See `references/cli-flags.md`.

## Minimal valid example

```json
{
  "name": "minimal",
  "description": "Read-only helper",
  "system_prompt": "Answer using tools. Do not modify files.",
  "tools": ["read_file", "shell_readonly"],
  "allowed_tools": ["read_file", "shell_readonly"],
  "max_turns": 20
}
```
