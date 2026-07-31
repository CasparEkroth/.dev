# Reference: paths

## Runtime discovery roots

| Kind | Path |
|------|------|
| System agents | `/etc/.amon/agents/*.json` |
| User agents | `~/.amon/agents/*.json` |
| Project agents | `$CWD/.amon/agents/*.json` |
| User skills (conventional) | `~/.amon/skills/<name>/SKILL.md` |
| User hooks (conventional) | `~/.amon/hooks/*` |
| Project skills/hooks | any path referenced by config / `skill://` |

## Repo paths (this codebase)

| Kind | Path |
|------|------|
| CLI | `scripts/amon/amon_cli.py` |
| Agent loop | `scripts/amon/agent_loop.py` |
| Hooks runner | `scripts/amon/hooks.py` |
| Agent model | `scripts/amon/tools/agent.py` |
| Tool registry | `scripts/amon/tools/registry.py` |
| Skills loader | `scripts/amon/tools/skills.py` |
| Sessions dir | `scripts/amon/config/sessions/` (via `config.SESSIONS_DIR`) |
| Setup installer | `scripts/amon/config/setup/install` |
| Bundled skill source | `scripts/amon/config/setup/python-validate/` |
| Human docs | `docs/amon/` |

## Installer outputs

`scripts/amon/config/setup/install` creates:

- `~/.amon/agents/default.json`
- `~/.amon/agents/planner.json`
- `~/.amon/skills/python-validate/`
- `~/.amon/hooks/log.sh`

## Docs examples

| Artifact | Path |
|----------|------|
| Minimal agent | `docs/amon/examples/minimal-agent.json` |
| Agent + hooks | `docs/amon/examples/agent-with-hooks.json` |
| Planner-like | `docs/amon/examples/readonly-planner.json` |
| Bash hook | `docs/amon/examples/hooks/log.sh` |
| Python hook | `docs/amon/examples/hooks/log.py` |
| Skill template | `docs/amon/examples/skills/SKILL.template.md` |
| This skill | `docs/amon/examples/skills/amon-author/` |
