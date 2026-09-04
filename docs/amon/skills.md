# Skills

Skills are on-demand instruction packages. The agent sees a **catalog** (name, description, path) in its system prompt, then must call `load_skill` before following a skill’s instructions.

Implementation: `scripts/amon/tools/skills.py`  
Prompt injection: `build_system_prompt` in `scripts/amon/agent_loop.py`  
Tool: `load_skill` in `scripts/amon/tools/registry.py`

## Layout

```text
~/.amon/skills/<skill-name>/
  SKILL.md              # required — frontmatter + instructions
  scripts/              # optional — helper scripts
  ...                   # optional resources discovered on load
```

Project-local skills also work if referenced via `skill://` paths.

## SKILL.md format

```markdown
---
name: python-validate
description: >-
  Use whenever Python code has been written or edited and needs to be checked…
---

# Python Validate

## Usage
…concrete commands…

## Instructions
1. …
2. …

## When NOT to use
- …
```

| Frontmatter | Required | Notes |
|-------------|----------|-------|
| `name` | recommended | Defaults to parent directory name |
| `description` | strongly recommended | Shown in the catalog; drives when the model loads the skill |

Body sections that work well for both humans and the agent:

- **Usage** — exact commands / tool calls
- **Instructions** — numbered steps
- **When NOT to use** — negative triggers

Reference: [amon-author reference](examples/skills/amon-author/references/skill-format.md).

## `skill://` URIs

Configured on the agent as `allowed_skills`:

```json
"allowed_skills": ["skill://~/.amon/skills/*/SKILL.md"]
```

| Form | Resolution |
|------|------------|
| `skill://.amon/skills/*/SKILL.md` | Relative to `base_dir` (default cwd) |
| `skill://~/.amon/skills/*/SKILL.md` | Home-expanded |
| `skill:///abs/path/skills/*/SKILL.md` | Absolute (triple slash) |

Globs supported via `glob(…, recursive=True)`.

## Runtime flow

1. `catalog_for_agent(agent.allowed_skills)` builds `[{name, description, path}, …]`
2. `build_system_prompt` appends an **Available Skills** section and instructs: `load_skill(skill_path=…)` must be called before acting on a matching skill's instructions — not necessarily as the very first tool call of the turn (e.g. setting up a checklist first is fine)
3. `load_skill` reads `SKILL.md` body + lists other files under the skill dir as `resources:`
4. Model follows the loaded instructions (often running a script path from `resources:`)

## Real skills to look at

- `python-validate` — shipped sample, installed by `scripts/amon/config/setup/install` (source: `scripts/amon/config/setup/python-validate/`)
- [amon-author](examples/skills/amon-author/SKILL.md) — creates/edits amon agents, hooks, and skills; also the canonical checklist for doing so (this guide doesn't repeat it)

## Writing skills for reliability

- Put **triggers** in `description` (“use when…”, “before claiming code works…”)
- Prefer **deterministic scripts** over “just inspect the file”
- Tell the model to use **resource paths from load output**, not hardcoded locations
- Skills under `~/.amon/skills` are shared; remember workspace `cwd` rules from the system prompt

Blank starting point: [examples/skills/SKILL.template.md](examples/skills/SKILL.template.md).
