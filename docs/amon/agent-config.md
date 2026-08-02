# Agent config

Agents are JSON files loaded at startup into `READY_AGENTS`.

## Load order

Later directories **override** same-named agents (same stem):

1. `/etc/.amon/agents/*.json`  (system)
2. `~/.amon/agents/*.json`     (user)
3. `$CWD/.amon/agents/*.json`  (project-local)

The map key is the **filename stem** (`default.json` → `--agent default`).

Invalid JSON / validation errors are skipped with a warning.

## Schema (overview)

Full field reference: [amon-author reference](examples/skills/amon-author/references/agent-schema.md).

```json
{
  "name": "default",
  "description": "Short summary shown in spawn_agents / pickers",
  "system_prompt": "Instructions for the model…",
  "tools": ["*"],
  "allowed_tools": ["shell_readonly", "read_file", "load_skill", "spawn_agents"],
  "allowed_skills": ["skill://~/.amon/skills/*/SKILL.md"],
  "hooks": {
    "start": "~/.amon/hooks/log.sh",
    "stop": "~/.amon/hooks/log.sh",
    "preToolUse": "~/.amon/hooks/log.sh",
    "postToolUse": "~/.amon/hooks/log.sh"
  },
  "max_turns": 50
}
```

### Field meanings

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Display / logical name |
| `description` | yes | Used in `spawn_agents` tool enum help text |
| `system_prompt` | yes | Base system prompt (skills section is appended at runtime) |
| `tools` | yes | Tools **registered** for this agent (schemas exposed to the model) |
| `allowed_tools` | yes | Subset that runs **without** confirmation (`requires_confirmation=False`) |
| `allowed_skills` | no | List of `skill://` URI patterns for the skill catalog |
| `hooks` | no | Map of hook event name → script path |
| `max_turns` | no | Max agent loop turns (default `10`, must be `> 0`) |

### `tools` vs `allowed_tools`

- `tools` — what the model **can see/call**
- `allowed_tools` — which of those skip the interactive confirm UI

Wildcard: `"*"` or `["*"]` expands to every key in `tool_registry` at load time.

Built-in tool names today:

- `shell`
- `shell_readonly`
- `read_file`
- `write_file`
- `load_skill`
- `spawn_agents` (registered after agents load)

## Project-local override pattern

```bash
mkdir -p .amon/agents
cp ~/.amon/agents/default.json .amon/agents/default.json
# edit tools / hooks / skills for this repo only
```

## Examples

- [examples/minimal-agent.json](examples/minimal-agent.json)
- [examples/agent-with-hooks.json](examples/agent-with-hooks.json)
- [examples/readonly-planner.json](examples/readonly-planner.json)

Ship/install defaults live in `scripts/amon/config/setup/install`.

Adding an agent step by step? The [amon-author skill](examples/skills/amon-author/SKILL.md) has the checklist.
