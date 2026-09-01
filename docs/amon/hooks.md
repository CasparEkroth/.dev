# Hooks

Hooks are external scripts the agent loop runs on lifecycle events. They are configured **per agent** via the `hooks` map in agent JSON.

Implementation: `scripts/amon/hooks.py`  
Called from: `scripts/amon/agent_loop.py`

## Events

| Event key (JSON) | Enum | When | Extra payload |
|------------------|------|------|---------------|
| `agentSpawn` | `HookEventName.AGENT_SPAWN` | First turn of a session, before the model is called | — |
| `start` | `HookEventName.START` | Before the model loop handles a user prompt | `prompt` |
| `stop` | `HookEventName.STOP` | When the model returns a final text answer, and when a run ends on a budget or a failed call | `response` |
| `preToolUse` | `HookEventName.PRE_TOOL_USE` | After confirmation, before the tool runs | `tool_name`, `tool_input` |
| `postToolUse` | `HookEventName.POST_TOOL_USE` | After the tool returns | `tool_name`, `tool_input`, `tool_output` |

`agentSpawn`, `start`, and `postToolUse` are **context-contributing**: their
stdout is appended to the conversation as a user message and persisted with
the session. For `agentSpawn`/`start` this lets an environment probe reach the
model without the agent having to run it; for `postToolUse` it lets a
test-gate style hook (e.g. running a linter/type-checker after `write_file`)
tell the model what broke, right after the turn's tool replies rather than
inside any one tool's own result.

## Configuration

Each event maps to a list of hook specs. A bare string or a list of strings is
accepted and normalized, so older configs keep working:

```json
{
  "hooks": {
    "agentSpawn": [{ "command": "~/.amon/hooks/probe.sh" }],
    "stop": ["~/.amon/hooks/log.sh", "~/.amon/hooks/score.sh"],
    "preToolUse": [
      { "command": "~/.amon/hooks/guard.sh", "matcher": "write_file", "timeout_ms": 2000 }
    ],
    "postToolUse": "~/.amon/hooks/log.sh"
  }
}
```

| Spec field | Required | Meaning |
|------------|----------|---------|
| `command` | yes | Script path (`~` expanded) |
| `matcher` | no | Glob against the tool name; pre/postToolUse only. No matcher runs for every tool |
| `timeout_ms` | no | Max run time, default 10000. On expiry the hook is abandoned |

Hooks on one event run in order. Missing scripts are skipped silently.

## Payload

The event is written to the hook's **stdin as JSON**:

```json
{
  "hook_event_name": "preToolUse",
  "cwd": "/current/working/directory",
  "session_id": "13e5ab9e-…",
  "tool_name": "write_file",
  "tool_input": { "content": [{ "path": "a.txt", "old": "", "new": "hi" }] }
}
```

The same values are also exported as environment variables — `SESSION_ID`,
`HOOK_EVENT_NAME`, `CWD`, plus the upper-cased extras (`TOOL_NAME`, `TOOL_INPUT`,
`TOOL_OUTPUT`, `PROMPT`, `RESPONSE`) — so env-reading hooks written before the
stdin payload still work.

## Exit codes

| Code | Effect |
|------|--------|
| 0 | Success. For `agentSpawn`/`start`/`postToolUse`, stdout joins the conversation |
| 2 | **preToolUse only**: block the tool. Stderr is returned to the model instead of the tool's result |
| other | Logged as a warning. The run continues — a hook can never break it |

## How scripts are executed

| File type | Command |
|-----------|---------|
| `*.py` | `sys.executable <path>` |
| executable (any other) | run path directly (needs shebang + `+x`) |
| non-executable other | `bash <path>` |

## Examples

See [examples/hooks/log.sh](examples/hooks/log.sh) and
[examples/hooks/log.py](examples/hooks/log.py).

Read the event from stdin:

```bash
#!/usr/bin/env bash
EVENT=$(cat)
echo "$EVENT" >> "${CWD:-.}/agent.log"
```

Block writes outside a directory:

```bash
#!/usr/bin/env bash
EVENT=$(cat)
case "$EVENT" in
  *'"path": "/etc/'*) echo "writes to /etc are not allowed" >&2; exit 2 ;;
esac
exit 0
```

Contribute environment facts to the agent's context:

```bash
#!/usr/bin/env bash
echo "python: $(command -v python3)"
echo "cwd: $(pwd)"
```

## What hooks are good for

- Audit logging (prompts, tools, responses)
- Environment discovery via `agentSpawn`, without spending a tool call
- Guardrails: block a tool with exit code 2 and tell the model why
- Test gates: after `write_file`, run a linter/type-checker/test suite via
  `postToolUse` and print failures to stdout so the model finds out before
  claiming the change works — see
  [examples/hooks/python_validate_gate.py](examples/hooks/python_validate_gate.py)
- Notifications or post-processing on `stop`

Adding a hook step by step? The [amon-author skill](examples/skills/amon-author/SKILL.md) has the checklist.
