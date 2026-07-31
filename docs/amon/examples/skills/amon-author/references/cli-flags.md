# Reference: CLI flags

Prog: `amon`  
Source: `scripts/amon/amon_cli.py`

## Mutually exclusive command group

| Flag | Type | Exit after | Description |
|------|------|------------|-------------|
| `--resume` / `-r` | bool | no | Interactive session picker, then REPL |
| `--resume-id` | UUID | no | Resume given session in REPL |
| `--list-sessions` | bool | yes | Print sessions |
| `--delete-session` | UUID | yes | Delete session |
| `--keep-N-sessions` / `-keep-n` | int | yes | Keep N newest sessions, delete rest |
| `--headless` | str (`INPUT`) | yes | Run one task non-interactively |

## Other flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--agent` | str | `default` | Agent stem in `READY_AGENTS` |
| `--save-session` | bool | false | **Headless only.** If set, persists the session; ignored in interactive mode, which always saves |

## Interactive-only commands

Not flags — REPL input:

- `/exit` | `/quit` | `/q`
- `/agent`
- `/sessions`
- `/new`
- `/compact`
