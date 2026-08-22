# Reference: hook events

Source: `scripts/amon/hooks.py`

## Event names

| JSON / env value | Enum member |
|------------------|-------------|
| `agentSpawn` | `HookEventName.AGENT_SPAWN` |
| `start` | `HookEventName.START` |
| `stop` | `HookEventName.STOP` |
| `preToolUse` | `HookEventName.PRE_TOOL_USE` |
| `postToolUse` | `HookEventName.POST_TOOL_USE` |

Use the JSON column as keys in agent config `hooks`.

## Payload

The event JSON is written to the hook's stdin:

| Key | Present |
|-----|---------|
| `hook_event_name` | always |
| `cwd` | always |
| `session_id` | always |
| `prompt` | `start` |
| `response` | `stop` |
| `tool_name`, `tool_input` | `preToolUse`, `postToolUse` |
| `tool_output` | `postToolUse` |

The same values are also exported as env vars: `SESSION_ID`, `HOOK_EVENT_NAME`,
`CWD`, plus upper-cased extras (`PROMPT`, `RESPONSE`, `TOOL_NAME`, `TOOL_INPUT`,
`TOOL_OUTPUT`).

## Spec fields

| Field | Default | Meaning |
|-------|---------|---------|
| `command` | — | Script path, `~` expanded |
| `matcher` | none | Glob on tool name; pre/postToolUse only |
| `timeout_ms` | 10000 | Abandoned on expiry |

## Execution

| Condition | How run |
|-----------|---------|
| path missing | no-op |
| suffix `.py` | `python path` (current interpreter) |
| executable | `path` |
| else | `bash path` |

## Exit codes

| Code | Effect |
|------|--------|
| 0 | stdout joins the conversation for `agentSpawn` / `start` |
| 2 | `preToolUse` only: blocks the tool, stderr goes to the model |
| other | logged as a warning; the run continues |

## Agent config snippet

```json
"hooks": {
  "agentSpawn": [{ "command": "~/.amon/hooks/probe.sh" }],
  "stop": ["~/.amon/hooks/log.sh", "~/.amon/hooks/score.sh"],
  "preToolUse": [{ "command": "~/.amon/hooks/guard.sh", "matcher": "write_file" }],
  "postToolUse": "~/.amon/hooks/log.sh"
}
```

A bare string or a list of strings is normalized to the spec form.
