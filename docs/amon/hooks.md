# Hooks

Hooks are external scripts the agent loop runs on lifecycle events. They are configured **per agent** via the `hooks` map in agent JSON.

Implementation: `scripts/amon/hooks.py`  
Called from: `scripts/amon/agent_loop.py`

## Events

| Event key (JSON) | Enum | When | Extra env |
|------------------|------|------|-----------|
| `start` | `HookEventName.START` | Before the model loop handles a user prompt | `PROMPT` |
| `stop` | `HookEventName.STOP` | When the model returns a final text answer (no more tools), and again if the loop exits without a final message path | `RESPONSE` |
| `preToolUse` | `HookEventName.PRE_TOOL_USE` | After confirmation, before the tool runs | `TOOL_NAME`, `TOOL_INPUT` |
| `postToolUse` | `HookEventName.POST_TOOL_USE` | After the tool returns | `TOOL_NAME`, `TOOL_INPUT`, `TOOL_OUTPUT` |

Always set for every event:

| Env var | Meaning |
|---------|---------|
| `SESSION_ID` | Current session UUID |
| `HOOK_EVENT_NAME` | Event name string (`start`, `stop`, `preToolUse`, `postToolUse`) |
| `CWD` | Working directory passed by the agent loop |

Details: [amon-author reference](examples/skills/amon-author/references/hook-events.md).

## Wiring hooks on an agent

```json
{
  "hooks": {
    "start": "~/.amon/hooks/log.sh",
    "stop": "~/.amon/hooks/log.sh",
    "preToolUse": "~/.amon/hooks/log.sh",
    "postToolUse": "~/.amon/hooks/log.sh"
  }
}
```

Paths are resolved with `Path(hook).expanduser().resolve()`. Missing files are silently skipped (`None`).

## How scripts are executed

| File type | Command |
|-----------|---------|
| `*.py` | `sys.executable <path>` |
| executable (any other) | run path directly (needs shebang + `+x`) |
| non-executable other | `bash <path>` |

Defaults: `timeout=30`, `check=True`, stdout/stderr captured. A failing script raises (subprocess error) — keep hooks reliable and fast.

## Minimal bash example

See [examples/hooks/log.sh](examples/hooks/log.sh).

```bash
#!/usr/bin/env bash
echo "$HOOK_EVENT_NAME session=$SESSION_ID" >> "${CWD:-.}/agent.log"
```

## Minimal Python example

See [examples/hooks/log.py](examples/hooks/log.py).

```python
import os
from pathlib import Path

log = Path(os.environ.get("CWD", ".")) / "agent.log"
with log.open("a") as f:
    f.write(f"{os.environ.get('HOOK_EVENT_NAME')} {os.environ.get('SESSION_ID')}\n")
```

## What hooks are good for

- Audit logging (prompts, tools, responses)
- Notifications (desktop, chat webhook) on `stop`
- Guardrails / extra policy checks around tools (note: failure currently errors the run)
- Appending session metadata to project files

Adding a hook step by step? The [amon-author skill](examples/skills/amon-author/SKILL.md) has the checklist.
