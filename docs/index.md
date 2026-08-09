# .dev docs

Developer documentation for the tools in this repo.

## Tools

| Tool | Docs | Status |
|------|------|--------|
| **amon** | [docs/amon/](amon/index.md) | active |
| **vector-index** | [docs/vector/](vector/index.md) | active |
| **search** | [docs/search.md](search.md) | active |
| **git-suggest** | [docs/git-suggest.md](git-suggest.md) | active |

## Reading amon's docs

**Just want to use amon?** Read these three and stop:

1. [Overview](amon/index.md) — what amon is and how the pieces fit
2. [CLI](amon/cli.md) — run sessions, headless mode, slash commands
3. [Agent config](amon/agent-config.md) — JSON agents under `~/.amon/agents`

**Customizing hooks or skills?** See [amon/index.md](amon/index.md#doc-map) for
the full map. The deep, machine-exact schemas live in the
[amon-author skill](amon/examples/skills/amon-author/SKILL.md) itself, not in
a separate reference doc.
