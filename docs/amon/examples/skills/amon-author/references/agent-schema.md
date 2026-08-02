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
| `max_turns` | int | no | `10` | must be `> 0` |

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
