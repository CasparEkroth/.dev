# amon examples

Copy-paste artifacts for docs, plus a real skill (`skills/amon-author/`) that
uses them.

| Path | What |
|------|------|
| `minimal-agent.json` | Smallest useful read-only agent |
| `readonly-planner.json` | Planner-style agent (mirrors install default) |
| `path-restricted-agent.json` | Repo-scoped allow/deny paths + denied shell commands |
| `agent-with-hooks.json` | Full tools + all four hook events |
| `hooks/log.sh` | Bash lifecycle logger |
| `hooks/log.py` | Python lifecycle logger |
| `skills/SKILL.template.md` | Blank skill skeleton |
| `skills/amon-author/` | Real, installable skill for creating/editing amon agents, hooks, and skills |

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
