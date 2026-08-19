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
  "max_turns": 50,
  "force_first_tool": false,
  "max_runtime_s": 900,
  "model": null,
  "max_tool_output_chars": null,
  "mcp_servers": {},
  "allow_paths": [],
  "deny_paths": [],
  "denied_commands": []
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
| `hooks` | no | Map of hook event name → list of `{command, matcher?, timeout_ms?}` specs. A bare string or list of strings is normalized to that form. `agentSpawn`/`start` stdout joins the conversation; a `preToolUse` hook exiting 2 blocks the tool |
| `max_turns` | no | Max agent loop turns (default `DEFAULT_MAX_TURNS` = 30, must be `> 0`) |
| `force_first_tool` | no | Require a tool call on the first turn (default `false`, so an agent can open with a clarifying question) |
| `max_runtime_s` | no | Wall-clock budget in seconds (default none). On expiry the run stops between turns and returns its partial result |
| `model` | no | Model id for this agent (default: `settings.LLM_MODEL`). Headless/`spawn_agents` can override per run via `--model` / job `model` |
| `system_prompt_template` | no | Overrides how the system prompt is assembled. Placeholders: `{prompt}` (this agent's `system_prompt`), `{workspace}` (cwd), `{skills}` (the catalog). Unused placeholders are fine; literal braces must be doubled, and an unknown placeholder raises at run start. Supply a template without the `load_skill` sentence to drop the skill mandate — e.g. when the agent's first tool call must be something else |
| `max_tool_output_chars` | no | Per-agent ceiling for tool-result truncation/spill. Default `null` uses global `MAX_TOOL_OUTPUT_CHARS` (20_000) |
| `mcp_servers` | no | **Stub** — accepted and validated, but no servers are started and no tools registered yet |
| `allow_paths` | no | Glob patterns of paths tools may touch. Empty (default) = unrestricted unless denied. Matched after `~` expansion and symlink/`..` resolution |
| `deny_paths` | no | Glob patterns of paths tools must not touch. Empty (default) = nothing denied. **Deny always wins over allow** |
| `denied_commands` | no | Literal command names blocked for `shell` / `shell_readonly` (checked in command position, including after `&&`/`;`/`|` in shell strings). Empty (default) = no extra restriction |

### Path / command restriction

Optional server-side guards bound onto tools at registry build time — **never**
exposed in the tool JSON schema, so the model cannot pass or override them.

A path is permitted iff it is **not** matched by any `deny_paths` pattern, **and**
(`allow_paths` is empty **or** matched by at least one `allow_paths` pattern).
Matching uses `fnmatch` against the resolved absolute path
(`Path(p).expanduser().resolve()`), so `../` traversal and symlinks that escape
an allowed tree are caught for `read_file` / `write_file`.

Enforcement points:

- `read_file` / `write_file` — every path argument is checked. This is a real
  boundary: those tools never shell out.
- `shell` / `shell_readonly` — `cwd` is checked against path rules, and
  command-position names against `denied_commands`. `shell_readonly` still
  applies its existing whitelist on top.

**Known limitation (load-bearing):** path/command restriction on `shell` can
only cover `cwd` and the literal command name(s). A permitted command can still
read/write paths outside any `allow_paths` tree via absolute paths or `cd`
inside the same invocation (e.g. `cat /etc/passwd`, `cd / && rm -rf whatever`).
Full containment needs OS-level sandboxing (container, chroot, bwrap), which is
out of scope. Treat `allow_paths` + `denied_commands` as a **guardrail against
accidental damage**, not a security sandbox for `shell`.

Example: [examples/path-restricted-agent.json](examples/path-restricted-agent.json).

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

Notable tool behaviour:

- `shell` takes `command` as an argv list **or** a shell string (pipes,
  redirects, `&&`), plus `timeout` (seconds, default `DEFAULT_SHELL_TIMEOUT`)
  and `shell`. Raise `timeout` for solvers, builds and test suites; when it
  expires the output captured so far is returned instead of lost. A shell
  string has no argv boundary, so prefer a list unless shell features are
  needed. `shell_readonly` takes `timeout` too, but no shell string — its
  whitelist is enforced on `command[0]`.
- `write_file` creates a file (and any missing parent directories) when the
  `path` does not exist, `old` is empty and `new` holds the content. For an
  existing file an empty `old` appends; otherwise the first occurrence of
  `old` is replaced. Pass `"overwrite": true` on an item to replace the
  file's entire contents with `new` in one call (creating it and parent
  directories if needed, `old` ignored) — use this for a full rewrite or a
  new implementation instead of chaining many small `old`/`new` patches.
- Every tool result is capped at `MAX_TOOL_OUTPUT_CHARS` (or the agent's
  `max_tool_output_chars` when set) before it enters the conversation. Longer
  output keeps its head and tail, and the full text is written to
  `TOOL_OUTPUT_DIR` (`AMON_TOOL_OUTPUT_DIR` overrides the path) with the path
  named in the inline marker, so the agent can read it back with `read_file`.
- `spawn_agents` runs each job as a child `amon --headless --json` process, at
  most `max_parallel` (default `DEFAULT_MAX_PARALLEL`) at a time. A job past
  `timeout_s` is killed. Optional job fields: `save_session`, `session_id`,
  `model`, `max_turns`. Optional top-level `output` writes the full result list
  JSON as a harness checkpoint even when some jobs fail. Children are separate
  processes, so one cannot corrupt shared state or outlive the parent.
- Session files live under `SESSIONS_DIR` (`AMON_SESSIONS_DIR` overrides).
- A run compacts its own history when the prompt crosses `COMPACT_AT_TOKENS`
  (75% of `BASE_CONTEXT_WINDOW`): everything before the last tool-calling turn
  is summarized by the same code path as `/compact`, so a long run keeps going
  instead of being rejected for exceeding the context window. The session file
  on disk stays complete. If a model call fails, the history is compacted and
  the turn retried once; if it fails again the run returns its partial result
  and error rather than losing everything.

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
- [examples/path-restricted-agent.json](examples/path-restricted-agent.json)

Ship/install defaults live in `scripts/amon/config/setup/install`.

Adding an agent step by step? The [amon-author skill](examples/skills/amon-author/SKILL.md) has the checklist.
