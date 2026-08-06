# amon

amon is an interactive coding agent with sessions, tool use, hooks, and skills.

## Quick start

```bash
# interactive (default agent)
amon

# headless one-shot
amon --headless "summarize the repo structure" --agent default

# headless JSON (pipe-clean stdout)
amon --headless "summarize the repo structure" --json

# resume / manage sessions
amon --list-sessions
amon --list-agents
amon --resume
amon --resume-id <uuid>
```

Default install writes agents and the sample skill via:

```bash
scripts/amon/config/setup/install
```

That creates:

- `~/.amon/agents/default.json`
- `~/.amon/agents/planner.json`
- `~/.amon/skills/python-validate/`
- `~/.amon/hooks/log.sh`

That's enough to start using amon. Everything below is for customizing it
(agents, hooks, skills).

## Mental model

```
CLI (amon)
  └─ loads Agent JSON  (name, prompt, tools, skills, hooks)
       └─ agent loop
            ├─ tools     (shell, read_file, write_file, load_skill, …)
            ├─ skills    (catalog injected into system prompt; loaded on demand)
            └─ hooks     (start / preToolUse / postToolUse / stop)
```

## Doc map

- [CLI](cli.md) — flags, sessions, interactive commands, headless mode
- [Agent config](agent-config.md) — JSON schema, load order, tools vs allowed_tools
- [Hooks](hooks.md) — events, env vars, Python/bash examples
- [Skills](skills.md) — SKILL.md format, `skill://` URIs, catalog + load flow
- [examples/](examples/) — copy-paste agent/hook/skill artifacts

For creating or editing amon agents, hooks, or skills step by step — including
an agent doing it — use [amon-author](examples/skills/amon-author/SKILL.md)
directly instead of the checklists that used to live in each guide above.
Install it like any skill: `cp -r docs/amon/examples/skills/amon-author ~/.amon/skills/amon-author`.
