# search

Entry point: `scripts/search/search_cli.py` (installed as `search`).

Answers a question using local files as context, and pulls in live web
results via Tavily when the question needs current/external information.

## Usage

```bash
search "QUERY" [-f FILE | -d DIR] [-s SUFFIX...] [-e EXCLUDE_DIR...]
```

| Flag | Purpose |
|------|---------|
| `QUERY` | Question to ask (required, positional) |
| `-f`, `--file` | Single file to include as context |
| `-d`, `--dir` | Directory to scan for files (mutually exclusive with `-f`) |
| `-s`, `--suffix` | Suffixes to include when scanning `--dir`. Default: `.py .md .txt` |
| `-e`, `--exclude` | Directory names to skip when scanning. Default: `.venv node_modules .git __pycache__` |

If neither `-f` nor `-d` is given, the question is answered with no file
context at all.

## Examples

```bash
# ask about one file
search "why does this raise on empty input" -f shared/file_handler.py

# scan a directory, restrict to python files
search "how is the LLM client selecting a provider" -d shared -s .py

# a question the router will decide needs a live web search
search "what changed in the latest openai python sdk release"
```

## How it works

1. A router prompt looks at the query and any file context and decides
   `requires_search: true/false`.
2. If `true`, it calls Tavily (`scripts/search/search.py`) with a generated
   search query, then answers using files + search results.
3. If `false`, it answers from the file context alone.

The answer is rendered as Markdown in the terminal (via `rich`).

## Requirements

- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` (see `.env.example`) — used for
  both the routing decision and the final answer.
- `TAVILY_API_KEY` — only required if a query actually triggers the web
  search path. Queries answered from files alone don't need it.
