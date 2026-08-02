# Reference: hook events

Source: `scripts/amon/hooks.py`

## Event names

| JSON / env value | Enum member |
|------------------|-------------|
| `start` | `HookEventName.START` |
| `stop` | `HookEventName.STOP` |
| `preToolUse` | `HookEventName.PRE_TOOL_USE` |
| `postToolUse` | `HookEventName.POST_TOOL_USE` |

Use the JSON column as keys in agent config `hooks`.

## Environment variables

### Always

| Variable | Example |
|----------|---------|
| `SESSION_ID` | UUID string |
| `HOOK_EVENT_NAME` | `preToolUse` |
| `CWD` | absolute or process cwd string |

### Per event

| Event | Variables |
|-------|-----------|
| `start` | `PROMPT` |
| `stop` | `RESPONSE` |
| `preToolUse` | `TOOL_NAME`, `TOOL_INPUT` |
| `postToolUse` | `TOOL_NAME`, `TOOL_INPUT`, `TOOL_OUTPUT` |

Values are passed as strings through the process environment.

## Execution

| Condition | How run |
|-----------|---------|
| path missing | no-op |
| suffix `.py` | `python path` (current interpreter) |
| executable | `path` |
| else | `bash path` |
| timeout | 30s default |
| failure | `subprocess.run(..., check=True)` raises |

## Agent config snippet

```json
"hooks": {
  "start": "/Users/you/.amon/hooks/log.sh",
  "stop": "/Users/you/.amon/hooks/log.sh",
  "preToolUse": "/Users/you/.amon/hooks/log.sh",
  "postToolUse": "/Users/you/.amon/hooks/log.sh"
}
```

`~` in paths is expanded.
