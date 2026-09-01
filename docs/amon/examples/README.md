# amon examples

Copy-paste artifacts for docs, plus a real skill (`skills/amon-author/`) that
uses them.

| Path | What |
|------|------|
| `minimal-agent.json` | Smallest useful read-only agent |
| `readonly-planner.json` | Planner-style agent (mirrors install default) |
| `path-restricted-agent.json` | Repo-scoped allow/deny paths + denied shell commands |
| `agent-with-hooks.json` | Full tools (incl. `todo_write`) + lifecycle hooks |
| `agent-with-test-gate.json` | Gates every `write_file` through the `python-validate` skill via `postToolUse` |
| `hooks/log.sh` | Bash lifecycle logger |
| `hooks/log.py` | Python lifecycle logger |
| `hooks/python_validate_gate.py` | `postToolUse` test gate: runs `python-validate`'s `check.py` on written `.py` files, reports failures to the model |
| `skills/SKILL.template.md` | Blank skill skeleton |
| `skills/amon-author/` | Real, installable skill for creating/editing amon agents, hooks, and skills |

Install defaults from `scripts/amon/config/setup/install` also write
`default.json`, `planner.json`, and `dev.json` under `~/.amon/agents/`.
`default` and `dev` allow `todo_write` without confirmation; the planner stays
read-only (`read_file` + `shell_readonly` only).

## Install an example agent

```bash
cp docs/amon/examples/minimal-agent.json ~/.amon/agents/minimal.json
amon --agent minimal --headless "what is in README.md?"
```

## Install an example hook

```bash
mkdir -p ~/.amon/hooks
cp docs/amon/examples/hooks/log.sh ~/.amon/hooks/log.sh
chmod +x ~/.amon/hooks/log.sh
# then set hooks on an agent JSON — see agent-with-hooks.json
```

## Install the python-validate test gate

Requires the `python-validate` skill installed at `~/.amon/skills/python-validate/`
(the install script's `default`/`dev` agents ship it there already).

```bash
mkdir -p ~/.amon/hooks
cp docs/amon/examples/hooks/python_validate_gate.py ~/.amon/hooks/python_validate_gate.py
chmod +x ~/.amon/hooks/python_validate_gate.py
cp docs/amon/examples/agent-with-test-gate.json ~/.amon/agents/test-gated.json
amon --agent test-gated "add a function to utils.py"
```
