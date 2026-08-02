---
name: amon-author
description: >-
  Use when creating, editing, or validating amon agent configs
  (~/.amon/agents/*.json or project .amon/agents/*.json), hooks
  (~/.amon/hooks/*), or skills (~/.amon/skills/*/SKILL.md). Trigger on
  requests like "add an amon agent", "wire up a hook", "make an amon skill",
  "why isn't my agent loading". Do not use for tasks inside amon's own
  Python source (scripts/amon/) — that's regular code editing, not config
  authoring.
---

# amon-author

Creates and edits amon agent configs, hooks, and skills correctly on the
first try, by reading the closed schemas in `references/` instead of
guessing field names or event keys.

## Stable contracts

Read the relevant reference before writing JSON or wiring an event — these
are the source of truth, not the prose guides under `docs/amon/`:

1. Agent JSON fields — `references/agent-schema.md`
2. Hook event names + env vars — `references/hook-events.md`
3. Skill frontmatter + directory layout — `references/skill-format.md`
4. Path roots — `references/paths.md`
5. CLI flags — `references/cli-flags.md`

Copy a starting point from the sibling `examples/` directory (one level up:
`../../minimal-agent.json`, `../../agent-with-hooks.json`,
`../../readonly-planner.json`, `../../hooks/log.sh`, `../../hooks/log.py`)
rather than writing JSON from scratch.

## Create / edit an agent

1. Target path: `~/.amon/agents/<stem>.json` or project `.amon/agents/<stem>.json`
2. Check `references/agent-schema.md` for required fields: `name`,
   `description`, `system_prompt`, `tools`, `allowed_tools`
3. Only reference known tool names (or `*`) — see the "Known tool names"
   table in `references/agent-schema.md`
4. Keep `allowed_tools` a subset of the logical tool set the agent can call
5. If `hooks` is set, confirm each path exists (or create the hook first)
6. If `allowed_skills` is set, confirm the glob resolves to at least the
   intended `SKILL.md` file(s)
7. `max_turns` must be `> 0`
8. Write valid JSON — no trailing commas, no comments
9. Restart amon (or re-run headless) so `READY_AGENTS` reloads

## Create a hook

1. Place the script under `~/.amon/hooks/` or a project-local path
2. Implement only the documented event env vars (`references/hook-events.md`)
   — don't invent new ones
3. Exit 0 on success; finish well under the 30s default timeout
4. Wire it into the agent's `hooks` map using the exact JSON event keys:
   `start`, `stop`, `preToolUse`, `postToolUse`
5. Trigger the event (send a prompt, run a tool) and verify the side effect

## Create a skill

1. Directory: `<skills_root>/<name>/SKILL.md`
2. YAML frontmatter needs `name` and a trigger-heavy `description` — the
   description *is* what causes the model to load the skill, so write it as
   "use when X" / "trigger on Y" / "do not use for Z", not a summary
3. Body: numbered instructions + concrete usage commands (see
   `../SKILL.template.md` for a blank skeleton)
4. Put deterministic helper scripts under `scripts/`; reference them by the
   relative path amon prints in the `resources:` block after `load_skill`,
   never a hardcoded machine path
5. Confirm some agent's `allowed_skills` glob covers the new skill directory
6. Restart amon (catalog is built at agent-load time) and confirm
   `load_skill` gets called for a matching prompt

## Validating before you finish

- Parse the agent JSON (`python3 -m json.tool <file>`) to catch syntax errors
- Re-read `references/agent-schema.md` and check every required field is
  present and every `tools`/`allowed_tools` entry is a real registry key
- For hooks, run the script manually once with the documented env vars set,
  confirm exit code 0
- If safe, run a dry `amon --headless "<trivial prompt>" --agent <stem>` to
  confirm the agent loads and responds

## Out of scope

- Editing amon's Python implementation itself (`scripts/amon/`) — that's
  regular source-code work, not config authoring
- Session/memory file internals
- LLM provider setup (`config.py` / root `.env`) — unrelated to agent,
  hook, or skill authoring
