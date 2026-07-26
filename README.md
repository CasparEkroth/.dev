# .dev

`.dev` is a small collection of developer-focused command line tools.

The current setup installs Python-based scripts into your local bin directory
as shell commands you can run from anywhere. Today the repo ships with
`git-suggest`, `vector-index`, `search` and `amon`.

It also includes a ready-to-use Neovim config under `scripts/nvim_config/`.


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

The installer currently creates the commands listed in the `scripts/bin` and places it in
`~/.local/bin`.

If `~/.local/bin` is not on your `PATH`, the setup script will try to add it to
`~/.zshrc` and tell you to reload your shell.

### Neovim config

This repo also ships a Python-focused Neovim setup (LSP, completion, file tree,
Treesitter, and more) in `scripts/nvim_config/`.

Install it with:

```bash
chmod +x scripts/nvim_config/setup_nvim
./scripts/nvim_config/setup_nvim
```

That copies `init.lua` and `lazy-lock.json` into `~/.config/nvim/`. On first
launch, Neovim/lazy.nvim will install the configured plugins.

Requires Neovim and `git`.

## Use

Use the installed commands from anywhere once `~/.local/bin` is on your `PATH`.

Current command:

- `git-suggest`: prints a suggested commit message and copies it to your clipboard. It takes no arguments and only uses your current directory and git. `Note:` *it bases its massage on the staged files* 

- `vector-index`: creates vector embeddings for a repository or PDF (**soon**) and can search an existing vector file by semantic similarity.

- `search`: semantic search over your codebase.

- `amon`: interactive coding agent with session management, tool use and headless mode.

## Extending The Toolset

This repo is meant to grow. To add more developer tools:

1. Add a new script under `scripts/`
2. Make it executable if needed
3. Update `setup` to install the new command into `~/.local/bin`
4. Re-run `./setup`


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
- Neovim (only needed for the optional nvim config install)
