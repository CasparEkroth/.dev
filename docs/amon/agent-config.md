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
  "allowed_tools": ["shell_readonly", "read_file", "load_skill", "spawn_agents", "todo_write"],
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

Wildcard: `"*"` or `["*"]` expands to every key in `tool_registry`, resolved
when `get_registry` builds the agent's tools (not when the agent config
loads) — this is what makes `spawn_agents` actually reachable from a
wildcard agent, since it's only added to `tool_registry` after agents load.

Built-in tool names today:

- `shell`
- `shell_readonly`
- `read_file`
- `write_file`
- `load_skill`
- `todo_write`
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
- `todo_write` sets/replaces the checklist of steps for the current task.
  Shape: `todos: [{content, status}]` with `status` in
  `pending` / `in_progress` / `completed`. Each call replaces the **entire**
  list (resend items you keep); the result echoes the list rendered so there
  is no separate read tool. Bad items are skipped with a note rather than
  failing the whole call. Convention (advisory): at most one `in_progress`
  item at a time. The current session id is bound **server-side** via
  `get_registry` (not a model-visible parameter). With a session id, the list
  is written to `{session_id}.todos.json` under `SESSIONS_DIR` (same dir as
  the transcript; see `save_todos` / `load_todos` in `memory.py`). That means
  it **survives `--resume`**, is cleaned up by `remove_session` / `--delete-session`,
  is excluded from session listings, and is shared with `spawn_agents`
  children that reuse the same `session_id` (separate processes, same disk
  sidecar). Headless runs with no session id fall back to a per-process
  in-memory store. On resume, `run_agent` re-injects any saved checklist into
  the conversation before the first model call. Confirmation still follows
  `allowed_tools` like other tools (shipped `default` / `dev` include it).
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
  processes, so one cannot corrupt shared state or outlive the parent. To share
  a checklist across parent and child, pass the same `session_id` on the job.
- Session artifacts live under `SESSIONS_DIR` (`AMON_SESSIONS_DIR` overrides):
  transcript file `{uuid}`, token meta `{uuid}.meta.json`, and optional todo
  sidecar `{uuid}.todos.json`.
- Loading a session (resume, or any run with a `session_id`) strips any
  unfinished tool cycle from the transcript before it's sent to the model.
  An interrupt (Ctrl+C, crash) can land between persisting an assistant's
  `tool_calls` and appending the matching `role: tool` replies; resending
  that half-formed pair breaks the next API call. The strip is a no-op for a
  session that ended cleanly, and it only affects what's sent to the model —
  the file on disk is untouched.
- **Prompt compaction**:
  - **Auto (during a run):** when the last turn's `prompt_tokens` crosses
    `COMPACT_AT_TOKENS` (75% of `BASE_CONTEXT_WINDOW`), or as a retry after a
    failed model call. Unfinished tool cycles are stripped first so the model
    never sees a half tool-call/result pair; everything before the last complete
    tool-calling turn is LLM-summarized via `compact_conversation`; the complete
    tail is kept. This only rewrites the in-memory conversation — the session
    file on disk stays complete.
  - **Hard trim** fallback (`_force_hard_trim`, keep last ~12 messages plus at
    most one leading system message) when the summary is unusable or a retry
    still fails — a long run keeps going instead of dying on context overflow.
  - If compaction and hard trim cannot recover after a retry, the run returns
    its partial result and error rather than losing everything.
  - **Interactive `/compact`:** now shares `_compact_history` with
    auto-compact (same unfinished-tool-cycle strip, same safe-tail handling),
    then **rewrites** the session file with the result (`override=True`). No
    hard-trim fallback here — if the summary call fails, `/compact` reports
    failure and leaves the on-disk transcript untouched, rather than falling
    back to a lossy trim the user didn't ask for.

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
