# .dev

`.dev` is a small collection of developer-focused command line tools.

The current setup installs Python-based scripts into your local bin directory
as shell commands you can run from anywhere. Today the repo ships with
`git-suggest`, `vector-index`, `search` and `amon`.

Longer-form docs live under [`docs/`](docs/index.md).


## What It Does

- Creates a local Python virtual environment
- Installs the project dependencies
- Exposes the available scripts as executable commands
- Copies the installed command into `~/.local/bin`

## Install

```bash
chmod +x setup
./setup
```

Install everything, or only specific commands by name:

```bash
./setup              # install all commands
./setup amon         # install only amon
./setup amon search  # install amon and search
./setup --help       # list available commands
```

The installer links commands from `scripts/bin` into `~/.local/bin`.

If `~/.local/bin` is not on your `PATH`, the setup script will try to add it to
`~/.zshrc` and tell you to reload your shell.

## Use

Use the installed commands from anywhere once `~/.local/bin` is on your `PATH`.

Current command:

- `git-suggest`: prints a suggested commit message and copies it to your clipboard. It takes no arguments and only uses your current directory and git. `Note:` *it bases its massage on the staged files*

- `vector-index`: creates vector embeddings for a repository or PDF (**soon**) and can search an existing vector file by semantic similarity.

- `search`: semantic search over your codebase.

- `amon`: interactive coding agent with session management, tool use and headless mode. See [docs/amon/](docs/amon/index.md).

## Documentation

Tool docs and examples are in [`docs/`](docs/index.md):

| Tool | Docs | Status |
|------|------|--------|
| **amon** | [docs/amon/](docs/amon/index.md) | active |
| **vector-index** | [docs/vector/](docs/vector/index.md) | active |
| **search** | [docs/search.md](docs/search.md) | active |
| **git-suggest** | [docs/git-suggest.md](docs/git-suggest.md) | active |

For amon specifically, start with the [overview](docs/amon/index.md), [CLI](docs/amon/cli.md), and [agent config](docs/amon/agent-config.md).

## Extending The Toolset

This repo is meant to grow. To add more developer tools:

1. Add a new script under `scripts/`
2. Make it executable if needed
3. Update `setup` to install the new command into `~/.local/bin`
4. Re-run `./setup`
5. Add or update docs under `docs/` when the tool is ready to document


## Development

```bash
make install
make lint
make format
make test
```

## Requirements

- Python 3
- `git`
- A shell that can run the `setup` script
