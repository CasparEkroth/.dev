---
name: my-skill
description: >-
  Use when <explicit trigger conditions>. Also trigger if the user says
  <phrases>. Do not use for <negative cases>.
---

# My Skill

Short intro of what this skill does and why the agent should run the script
instead of improvising.

## Usage

Resource paths are listed under `resources:` after `load_skill`. Use those paths;
do not hardcode machine-specific locations.

```bash
python <path-from-resources> <args>
```

## Instructions

1. Call `load_skill` on this skill directory first (already required by amon).
2. Run the usage command with the resource path from the loaded skill output.
3. Read the command output and act on failures before claiming success.
4. Re-run after fixes when applicable.

## When NOT to use

- …
