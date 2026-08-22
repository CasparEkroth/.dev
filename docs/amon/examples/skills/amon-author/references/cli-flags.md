# Reference: CLI flags

Prog: `amon`  
Source: `scripts/amon/amon_cli.py`

## Mutually exclusive command group

| Flag | Type | Exit after | Description |
|------|------|------------|-------------|
| `--resume` / `-r` | bool | no | Interactive session picker, then REPL |
| `--resume-id` | UUID | no | Resume given session in REPL |
| `--list-sessions` | bool | yes | Print sessions |
| `--list-agents` | bool | yes | Print loaded agents (`- name: description` per line, or `No agents configured.`) |
| `--delete-session` | UUID | yes | Delete session |
| `--keep-N-sessions` / `-keep` | int | yes | Keep N newest sessions, delete rest |
| `--headless` | str (`INPUT`) | yes | Run one task non-interactively |

## Other flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--agent` | str | `default` | Agent stem in `READY_AGENTS` |
| `--json` | bool | false | **Headless only.** Dump the headless payload as JSON on stdout (indent=2, pipe-clean; no rich/spinner on stdout). Exit `0` if `payload.ok` else `1`. Single job → that result dict; multiple → `{ok, results}`. Rejected without `--headless`. `usage` is full-run summed tokens. |
| `--save-session` | bool | false | **Headless only.** If set, persists the session; ignored in interactive mode, which always saves. Raw `spawn_agents` jobs also default `save_session=false`. |
| `--session-id` | UUID | none | **Headless only.** Use this session id (resume transcript if the file exists). Rejected without `--headless`. |
| `--model` | str | none | **Headless only.** Override the agent model for this run only. Rejected without `--headless`. |
| `--max-turns` | int | none | **Headless only.** Override agent `max_turns` for this run only. Rejected without `--headless`. |
| `--stream` | bool | false | **Headless only.** Stream tool calls/results to stderr (sets `AMON_STREAM=1`). Keeps stdout pipe-clean when combined with `--json`. Rejected without `--headless`. |

## Environment variables (runtime paths / streaming)

These are read from the process environment (not CLI flags). Set them before launching `amon` (or before importing `config` in-process):

| Variable | Affects | Default |
|----------|---------|---------|
| `AMON_SESSIONS_DIR` | Session transcript directory (`config.SESSIONS_DIR`) | `scripts/amon/config/sessions/` under the repo |
| `AMON_TOOL_OUTPUT_DIR` | Spill directory for truncated tool output (`config.TOOL_OUTPUT_DIR`) | `scripts/amon/config/tool_output/` under the repo |
| `AMON_STREAM` | When non-empty, headless `Agent.run_task` streams tool events to stderr via `stream_action_stderr` | unset; `--stream` sets it to `1` |

## `spawn_agents` / headless job fields (not CLI flags)

Headless CLI builds one job dict; `spawn_agents` accepts a list. Shared optional job keys:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `agent` | str | required | Stem in `READY_AGENTS` |
| `task` | str | required | Prompt |
| `save_session` | bool | `false` | Persist session |
| `session_id` | UUID/str | none | External id (correlates logs; resumable) |
| `model` | str | none | Per-job model override |
| `max_turns` | int | none | Per-job turn cap override |

Top-level `spawn_agents` args (tool parameters, not CLI):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `jobs` | list | required | Job objects above |
| `max_parallel` | int | `DEFAULT_MAX_PARALLEL` (4) | Concurrent children |
| `timeout_s` | float | none | Kill child on wall-clock expiry |
| `output` | str path | none | Write full result list JSON even if some jobs failed (harness checkpoint) |

## Interactive-only commands

Not flags — REPL input:

- `/exit` | `/quit` | `/q`
- `/agent`
- `/sessions`
- `/new` — new session id; resets token/context footer **and** checklist toolbar
- `/compact` — LLM-summarize the session transcript and rewrite the session file with the summary (unlike auto-compact during a run, which keeps the on-disk transcript complete)

### Checklist toolbar

`todo_write` results update the bottom footer and a dedicated checklist panel.
On resume, footer seeds from `{session_id}.todos.json` when present. See
`docs/amon/cli.md` and `references/paths.md`.
