# vector-index

Entry point: `scripts/vector/vector_cli.py` (installed as `vector-index`).

Builds a local semantic vector store from a repo (or searches one). No
external vector DB — everything is a single JSON file.

## Subcommands

```bash
vector-index repo PATH [--out vectors.json]
vector-index search QUERY [-v vectors.json] [-k 10] [--json]
vector-index pdf PATH [--out vectors.json]   # not implemented yet
```

| Command | Purpose |
|---------|---------|
| `repo` | Index a directory's source files into a vector JSON file |
| `search` | Semantic search over an existing vector JSON file |
| `pdf` | Stub — prints "not implemented yet" and exits |

## `repo`

```bash
vector-index repo . --out vectors.json
```

For each file under `PATH` (skipping `EXCLUDED_DIRS` from `config.py`:
`.git`, `.venv`, `node_modules`, `dist`, `build`, caches, etc.):

1. Only files whose suffix is a supported language are indexed — currently
   **Python (`.py`), JavaScript (`.js`), Java (`.java`)**. Everything else is
   skipped entirely.
2. The whole file is summarized by the LLM and embedded as one `"file"` vector.
3. Tree-sitter (`scripts/vector/code/lang_adapters.py`) extracts functions and
   classes. Each symbol is summarized by the LLM and embedded individually
   (`"symbol"` vectors), so a search can land on a specific function instead
   of a whole file.
4. If a file has no extractable symbols, it's split into ~80-line chunks
   (10-line overlap) and each chunk is embedded directly, no LLM summary
   (`"chunk"` vectors).

This calls the LLM once per file plus once per extracted symbol — expect it
to be slow and to burn tokens on anything but a small repo.

Embeddings use `sentence-transformers/all-MiniLM-L6-v2` (downloaded on first
run; `HF_TOKEN` only matters if you point this at a gated model).

## `search`

```bash
vector-index search "how does the retry logic work" -v vectors.json -k 5
```

| Flag | Purpose |
|------|---------|
| `-v`, `--vec`, `--vectors` | Path to the vector JSON file (default `vectors.json`) |
| `-k`, `--top-k` | Number of results (default 10) |
| `--json` | Print raw JSON results instead of the formatted list |

Loads the vector file, embeds the query, ranks by cosine similarity, and
prints the top-k payloads (`path`, `kind`, `language`, line range, summary).

## `pdf`

Not implemented — the subcommand exists and validates its argument (must be
a `.pdf` file) but only prints a placeholder message.

## Requirements

- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` (see `.env.example`) — used by
  `repo` for file/symbol summaries. Not needed for `search`.
- First run downloads the `sentence-transformers` model, so it needs network
  access once and then works offline.
