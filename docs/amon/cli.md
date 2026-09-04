# CLI

Entry point: `scripts/amon/amon_cli.py` (installed as `amon`).

## Modes

| Mode | How | Behavior |
|------|-----|----------|
| Interactive | `amon` | REPL with slash commands, tool confirmation UI |
| Headless | `amon --headless "…"` | Single task via `spawn_agents`, prints result |
| Session admin | `--list-sessions`, `--delete-session`, `--keep-N-sessions` | No agent run |
| Agent admin | `--list-agents` | Print loaded agents and exit |

## Common invocations

```bash
amon
amon --agent planner
amon --resume
amon --resume-id 13e5ab9e-ab29-40e3-ade9-e4b316ffdf28
amon --list-sessions
amon --list-agents
amon --delete-session 13e5ab9e-ab29-40e3-ade9-e4b316ffdf28
amon --keep-N-sessions 5
amon --headless "list python packages in this repo" --agent default
amon --headless "list python packages in this repo" --json
amon --headless "…" --json --session-id 13e5ab9e-ab29-40e3-ade9-e4b316ffdf28
amon --headless "…" --json --model gpt-x --max-turns 20
amon --headless "…" --json --stream   # tool events on stderr
```

## Flags

Full table (exit behavior, types, defaults): [amon-author reference](examples/skills/amon-author/references/cli-flags.md).

| Flag | Purpose |
|------|---------|
| `--agent NAME` | Agent JSON stem to load (default: `default`) |
| `--resume` / `-r` | Pick a session interactively |
| `--resume-id UUID` | Resume a specific session |
| `--list-sessions` | Print sessions and exit |
| `--list-agents` | Print loaded agents (`name: description`) and exit |
| `--delete-session UUID` | Delete one session |
| `--keep-N-sessions N` / `-keep N` | Keep only N newest sessions |
| `--headless INPUT` | Non-interactive single prompt |
| `--json` | Headless only: print the result as JSON on stdout (pipe-clean). Errors if used without `--headless` |
| `--save-session` | Headless only: save the session (see below) |
| `--session-id UUID` | Headless only: use/resume this session id |
| `--model NAME` | Headless only: override agent model for this run |
| `--max-turns N` | Headless only: override agent max turns for this run |
| `--stream` | Headless only: stream tool calls/results to stderr (`AMON_STREAM=1`) |

Session saving differs by mode:

- **Interactive**: always saves — every turn runs with `save_session_=True` hardcoded.
- **Headless CLI**: does **not** save by default. Pass `--save-session` to persist.
- **`spawn_agents` (API/tool)**: also defaults `save_session=false` per job; set
  `save_session: true` on a job to persist.

Headless per-run overrides (CLI flags map 1:1 onto the job dict / `spawn_agents`
job fields):

- `--session-id` → `session_id` (resume transcript if present)
- `--model` → `model`
- `--max-turns` → `max_turns`
- `--stream` sets env `AMON_STREAM=1` so tool events go to stderr via
  `terminal.stream_action_stderr` (stdout stays clean with `--json`)

`spawn_agents` also accepts top-level `output` (checkpoint JSON path),
`max_parallel`, and `timeout_s`. Job fields: `save_session`, `session_id`,
`model`, `max_turns`.

Runtime directories (set **before** process start; bound at `config` import):

| Env | Default | Contents |
|-----|---------|----------|
| `AMON_SESSIONS_DIR` | `scripts/amon/config/sessions/` | Transcript `{uuid}`, meta `{uuid}.meta.json`, todos `{uuid}.todos.json` |
| `AMON_TOOL_OUTPUT_DIR` | `scripts/amon/config/tool_output/` | Spill files for truncated tool output |

Meta also carries `agent` and `preview` (recorded once, on a brand-new
session) — shown alongside the session id in `/sessions` and the `--resume`
picker instead of a bare UUID + timestamp.

Set `AMON_EVENTS=1` for opt-in structured logging (`{session_id}.events.jsonl`:
per-turn latency/usage, per-tool latency, compaction triggers). Off by
default. Details: [agent-config](agent-config.md#observability-amon_events).

## Interactive slash commands

Typed at the `>` prompt (must be exact matches unless noted):

| Command | Effect |
|---------|--------|
| `/exit`, `/quit`, `/q` | Leave the REPL |
| `/agent` | Pick another loaded agent |
| `/sessions` | List sessions |
| `/new` | Fresh session id + reset context footer **and** checklist toolbar |
| `/compact` | Summarize the session transcript into a structured summary (goal, done, open questions, key paths) and **rewrite** the session file with it (`save_session(…, override=True)`). Prints “Nothing to compact yet.” instead of calling the model when there's nothing worth summarizing (e.g. only the current, unanswered user turn) |

Unknown `/…` commands print a dim “not a command” message.

### Checklist UX (`todo_write`)

When the agent calls `todo_write`:

- Streaming UI shows a magenta **☑ Checklist** panel (not the generic tool-result panel).
- The bottom status footer keeps a live copy of the checklist lines under the token/context line.
- On `--resume` / `--resume-id`, `show_welcome` seeds the footer from any `{session_id}.todos.json` sidecar so the list is visible immediately, not only after the next tool call.
- `/new` clears the footer checklist via `reset_footer(todos=True)`.

Persistence details (disk sidecar, resume re-injection, sharing via `session_id`): [agent-config](agent-config.md).

## Session flow (interactive)

1. Resolve session id (new UUID, `--resume-id`, or picker via `--resume`)
2. Load agent from `READY_AGENTS[args.agent]`
   - If the resumed session's recorded agent (see `agent`/`preview` in
     [agent-config](agent-config.md)) differs from `--agent`, print a yellow
     warning and continue anyway — a mismatch is usually a forgotten
     `--agent` flag, not an intentional switch (that's what `/agent` is for)
3. Each user message calls `run_agent(…)` with:
   - `system_prompt` from agent config
   - tool registry from `tools` + `allowed_tools`
   - skill catalog from `allowed_skills`
   - `hooks` from agent config

## Headless flow

```text
amon --headless TASK --agent NAME [--json] [--save-session]
                 [--session-id UUID] [--model M] [--max-turns N] [--stream]
  → optional: AMON_STREAM=1 when --stream
  → run_jobs([{agent, task, save_session, session_id?, model?, max_turns?}])  # THIS process
  → Agent.run_task (headless=True; streams to stderr if AMON_STREAM)
  → print result (rich panels) or JSON if --json
```

The `spawn_agents` tool is the other direction: it launches `amon --headless
--json` children, capped and killable. Headless runs in-process so a child can
never spawn a grandchild. With `AMON_STREAM` set, each child's stderr is
forwarded live (not buffered until the whole batch finishes), and in the
interactive terminal a `spawn_agents` result renders as a table (agent, ok,
tokens, turns, session) instead of raw JSON when it parses cleanly.

### `--json` output

With `--headless --json`, amon writes a single JSON object to stdout (no spinner/rich
noise) and exits `0` on success / `1` on failure. Shape comes from `spawn_agents` via
`_headless_payload`:

```json
{
  "ok": true,
  "agent": "default",
  "task": "list python packages in this repo",
  "result": "…",
  "error": null,
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  },
  "turns": 1,
  "tools_used": [],
  "session_id": null
}
```

`usage` fields are **full-run sums** across turns (not last-turn only).
When `ok` is false (unknown agent, exception, max turns), check `error`; `result`
may still hold partial content (especially on max-turns).

If multiple jobs were spawned, the payload is `{ "ok": <all ok>, "results": [ … ] }`.
Without `--json`, the same data is rendered with `terminal.print_headless_result`.
`--json` without `--headless` is rejected by the CLI.

## Sample output

`--list-sessions` (`terminal.print_sessions`):

![Session list output](assets/cli-list-sessions.png)

`--list-agents` prints one line per loaded agent from `READY_AGENTS` (`_AGENT_DESCRIPTION_STR`):

```text
- default: General-purpose default agent with access to all available tools and skills…
- planner: Takes a task and restructures it into a clear, ordered step-by-step plan…
```

If none are configured, it prints `No agents configured.`

`--headless` result (`terminal.print_headless_result`) — one panel per job, title
`agent — task`, body as Markdown, then a dim meta line when available:

```text
╭─ default — list python packages in this repo ────────────────────╮
│ Found 3 packages: shared, scripts.amon, config                   │
╰──────────────────────────────────────────────────────────────────╯
tokens=1434 · turns=3 · tools=shell_readonly, read_file
```

Failed jobs use a red panel with `error` instead of the result body.

Interactive mode opens with a welcome panel (`terminal.show_welcome`) showing the
agent name and slash-command hints, then replays prior turns if `--resume`/`--resume-id`
loaded an existing session. If that session has a saved checklist, the footer is
seeded from it. A footer tracks token usage against the context limit fetched once
at startup via `_init_context_limit` (`get_context_window`), plus any active
checklist lines.

Long runs compact automatically when prompt tokens cross `COMPACT_AT_TOKENS`, with
a hard-trim fallback on overflow — auto-compact keeps the on-disk session file
complete (in-memory only). Interactive `/compact` is different: it rewrites the
session file to the summary. Details: [agent-config](agent-config.md).

Ctrl+C during an interactive run requests a **graceful stop**: the current step
(in-flight LLM call or tool call) still finishes, then the partial run is
persisted and returned as a normal, non-ok `AgentResult` (`error="Interrupted."`,
same shape as hitting `max_turns`/`max_runtime_s`). A second Ctrl+C while still
running hard-aborts immediately (`KeyboardInterrupt`, no delayed receive of the
in-flight LLM response), same as the old single-press behavior. ESC is not a
cancel key.
