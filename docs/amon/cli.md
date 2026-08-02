# CLI

Entry point: `scripts/amon/amon_cli.py` (installed as `amon`).

## Modes

| Mode | How | Behavior |
|------|-----|----------|
| Interactive | `amon` | REPL with slash commands, tool confirmation UI |
| Headless | `amon --headless "…"` | Single task via `spawn_agents`, prints result |
| Session admin | `--list-sessions`, `--delete-session`, `--keep-N-sessions` | No agent run |

## Common invocations

```bash
amon
amon --agent planner
amon --resume
amon --resume-id 13e5ab9e-ab29-40e3-ade9-e4b316ffdf28
amon --list-sessions
amon --delete-session 13e5ab9e-ab29-40e3-ade9-e4b316ffdf28
amon --keep-N-sessions 5
amon --headless "list python packages in this repo" --agent default
```

## Flags

Full table (exit behavior, types, defaults): [amon-author reference](examples/skills/amon-author/references/cli-flags.md).

| Flag | Purpose |
|------|---------|
| `--agent NAME` | Agent JSON stem to load (default: `default`) |
| `--resume` / `-r` | Pick a session interactively |
| `--resume-id UUID` | Resume a specific session |
| `--list-sessions` | Print sessions and exit |
| `--delete-session UUID` | Delete one session |
| `--keep-N-sessions N` / `-keep-n N` | Keep only N newest sessions |
| `--headless INPUT` | Non-interactive single prompt |
| `--save-session` | Headless only: save the session (see below) |

Session saving differs by mode:

- **Interactive**: always saves — every turn runs with `save_session_=True` hardcoded.
- **Headless**: does **not** save by default. Pass `--save-session` to persist the
  session (threaded through `spawn_agents` → `Agent.run_task(save_session=...)`).

## Interactive slash commands

Typed at the `>` prompt (must be exact matches unless noted):

| Command | Effect |
|---------|--------|
| `/exit`, `/quit`, `/q` | Leave the REPL |
| `/agent` | Pick another loaded agent |
| `/sessions` | List sessions |
| `/new` | Fresh session id + reset context footer |
| `/compact` | LLM-summarize the current session transcript |

Unknown `/…` commands print a dim “not a command” message.

## Session flow (interactive)

1. Resolve session id (new UUID, `--resume-id`, or picker via `--resume`)
2. Load agent from `READY_AGENTS[args.agent]`
3. Each user message calls `run_agent(…)` with:
   - `system_prompt` from agent config
   - tool registry from `tools` + `allowed_tools`
   - skill catalog from `allowed_skills`
   - `hooks` from agent config

## Headless flow

```text
amon --headless TASK --agent NAME
  → spawn_agents([{agent: NAME, task: TASK}])
  → Agent.run_task (headless=True)
  → print result
```

## Sample output

`--list-sessions` (`terminal.print_sessions`):

![Session list output](assets/cli-list-sessions.png)

`--headless` result (`terminal.print_headless_result`) — one panel per job, titled
`agent:task`, body rendered as Markdown:

```text
╭─ default:list python packages in this repo ──────────────────────╮
│ Found 3 packages: shared, scripts.amon, config                   │
╰────────────────────────────────────────────────────────────────╯
```

Interactive mode opens with a welcome panel (`terminal.show_welcome`) showing the
agent name and slash-command hints, then replays prior turns if `--resume`/`--resume-id`
loaded an existing session. A footer tracks token usage against the context limit
fetched once at startup via `_init_context_limit` (`get_context_window`).
