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
| `hooks` | object | no | `{}` | keys → script path strings |
| `max_turns` | int | no | `DEFAULT_MAX_TURNS` (30) | must be `> 0` |
| `force_first_tool` | bool | no | `false` | Require a tool call on turn 0; off means the agent may open with a question |
| `max_runtime_s` | float | no | `null` | Wall-clock budget; the run stops between turns and keeps its partial result |
| `model` | string | no | `null` | Model id for this agent; falls back to `settings.LLM_MODEL` |
| `mcp_servers` | object | no | `{}` | **STUB** — validated and ignored until MCP support lands |

## `mcp_servers` (stub)

Accepted so configs written now keep working, but nothing is connected yet: the
servers are not started and their tools are not registered. Entry shapes follow
the usual conventions — local `{command, args, env, timeout, disabled,
disabledTools}`, remote `{url, headers, oauth, oauthScopes}`.

## `hooks` object keys

Exact strings (see hook events reference):

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
- `spawn_agents`

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
