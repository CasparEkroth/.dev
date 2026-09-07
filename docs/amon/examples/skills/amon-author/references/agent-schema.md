# Reference: agent JSON schema

Source model: `scripts/amon/tools/agent.py` → class `Agent`

## File locations

By default, configs are **merged** from three roots (later wins on stem collision):

| Priority (low → high) | Glob |
|-----------------------|------|
| 1 system | `/etc/.amon/agents/*.json` |
| 2 user | `~/.amon/agents/*.json` |
| 3 project | `$CWD/.amon/agents/*.json` |

Map key = filename stem. Higher priority overwrites lower on conflict. A
project-local tree alone does **not** hide home/system agents.

When `AMON_CONFIG_ROOT` is set, loading uses *only*
`<AMON_CONFIG_ROOT>/agents` (system/home/cwd skipped) — hermetic isolation
for CI/verify.

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
| `mcp_servers` | object | no | `{}` | `server_name` → config; discovered and merged into the tool registry per run (see below) |
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

## `mcp_servers`

Source: `scripts/amon/tools/mcp.py` (`discover_mcp_tools`). Each key is a
server name; the value is one of:

| Field | Transport | Meaning |
|-------|-----------|---------|
| `command` | stdio | Executable to spawn (required for stdio) |
| `args` | stdio | Argv list passed to `command`. Default `[]` |
| `env` | stdio | Extra env vars for the child process. `${VAR_NAME}` expands against the *host* process env at connect time — never persisted back to disk, never logged |
| `url` | remote (SSE) | Server endpoint (required for remote; mutually exclusive with `command`) |
| `headers` | remote | Request headers, e.g. `{"Authorization": "Bearer ${MY_TOKEN}"}`. Same `${VAR}` expansion as `env` |
| `timeout` | both | Seconds for one connect + `tools/list`/`tools/call` + close cycle (reconnect path), or per bridged call on a persistent connection. Default `DEFAULT_MCP_TIMEOUT` (30s, `config.py`) |
| `disabled` | both | `true` skips connecting to this server entirely |
| `disabledTools` | both | Tool names from this server to drop after discovery |
| `persistent` | both | `true` keeps one connection alive for the run/session instead of reconnecting per call. Default `false`. Required for servers that hold state across calls (e.g. browser automation like `@playwright/mcp`) |
| `oauth` / `oauthScopes` | remote | **Reserved, not yet implemented.** Accepted and ignored — v1 remote auth is `headers` only |

Discovery runs once per agent load (not per prompt): `Agent.run_task()` awaits
it before building the tool registry; the interactive CLI does it on initial
agent load and on `/agent` switch. Discovered tools are named
`mcp__{server_name}__{tool_name}` and merged into the registry exactly like a
native tool — `tools: ["*"]` picks them up automatically, and
`allowed_tools` / path guards / hooks / `AMON_EVENTS` all apply unchanged. A
server that's unreachable or times out during discovery is logged and
skipped rather than failing the whole agent run; a bad per-tool call (`is_error`
from the server) comes back as a normal `"Error: ..."` tool result, not a
raised exception.

**Default connection model is reconnect-per-call**: one
connect/`initialize`/`tools/call`/close cycle per tool invocation. Simple and
correct under `spawn_agents`' multi-process model; a chatty MCP tool (many
calls per turn) pays a reconnect each time. Opt in to a persistent background
session per server with `"persistent": true` — one connection for the headless
run (or interactive agent session until `/agent` switch / exit). See
MCP_SUPPORT_PLAN.md §1.2.

Worked example — a local stdio server and a remote SSE server on one agent:

```json
"mcp_servers": {
  "git": {
    "command": "mcp-server-git",
    "args": ["--repository", "."],
    "disabledTools": ["git_push"]
  },
  "internal-api": {
    "url": "https://mcp.example.com/sse",
    "headers": { "Authorization": "Bearer ${INTERNAL_MCP_TOKEN}" },
    "timeout": 10
  }
}
```

With that config, `tools: ["*"]` exposes `mcp__git__git_status`,
`mcp__git__git_diff`, etc. (minus `git_push`), plus whatever
`internal-api` lists — each still going through the normal confirm UI unless
also listed in `allowed_tools`.

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
- `set_cwd`
- `spawn_agents` (registered after agents load)
- `mcp__{server_name}__{tool_name}` (per-agent, discovered from `mcp_servers` — not in the static registry)

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
