"""System-prompt assembly for agent runs."""

from __future__ import annotations

from pathlib import Path

#: Placeholders: {prompt}, {workspace}, {skills}. An agent can replace this via
#: `system_prompt_template` — e.g. to drop the load_skill mandate. Literal braces
#: in a custom template must be doubled.
DEFAULT_SYSTEM_PROMPT_TEMPLATE = """{prompt}

## Workspace
The project working directory is: {workspace}
Skills live under ~/.amon/skills and are shared across projects — their paths are \
absolute and unrelated to the workspace. When running `shell`/`shell_readonly` \
commands (e.g. invoking a skill's script), always pass `cwd={workspace}` \
(or a path inside it) unless the user asks you to operate elsewhere. Never infer \
cwd from a skill's path.

## Available Skills
{skills}

When the user's request matches one of the above skills, load it with \
`load_skill(skill_path=<path>)` before following any of its instructions — do \
not run shell commands or read files as part of that skill's workflow until \
it's loaded. This doesn't have to be your very first tool call of the turn \
(e.g. setting up a checklist first is fine); it must come before you start \
acting on the skill itself."""


def build_system_prompt(
    base_prompt: str,
    skill_catalog: list[dict] | dict,
    template: str | None = None,
) -> str:
    """Assemble the system prompt from *template* (or the default one)."""
    skills_section = "\n".join(
        f"- {s['name']} (skill_path: {s['path']}): {s['description']}"
        for s in skill_catalog
    )
    return (template or DEFAULT_SYSTEM_PROMPT_TEMPLATE).format(
        prompt=base_prompt, workspace=Path.cwd(), skills=skills_section
    )
