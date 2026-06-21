# .dev

`.dev` is a small collection of developer-focused command line tools.

The current setup installs Python-based scripts into your local bin directory
as shell commands you can run from anywhere. Today the repo ships with
`git-suggest`, a helper that generates a commit message from your current git
status and diff.

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

The installer currently creates the `git-suggest` command and places it in
`~/.local/bin`.

If `~/.local/bin` is not on your `PATH`, the setup script will try to add it to
`~/.zshrc` and tell you to reload your shell.

## Use

Use the installed commands from anywhere once `~/.local/bin` is on your `PATH`.

Current command:

- `git-suggest`: prints a suggested commit message and copies it to your clipboard. It takes no arguments and only uses your current directory and git

## Extending The Toolset

This repo is meant to grow. To add more developer tools:

1. Add a new script under `scripts/`
2. Make it executable if needed
3. Update `setup` to install the new command into `~/.local/bin`
4. Re-run `./setup`

That keeps the workflow simple: the installer becomes the single place that
decides which commands are available.

## Development

```bash
make install
make lint
make format
```

## Requirements

- Python 3
- `git`
- A shell that can run the `setup` script
