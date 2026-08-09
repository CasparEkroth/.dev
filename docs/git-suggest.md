# git-suggest

Entry point: `scripts/git_suggest.py` (installed as `git-suggest`).

Prints a suggested commit message for your **staged** changes and copies it
to the clipboard.

## Usage

```bash
git add <files>
git-suggest
```

Takes no arguments. It runs `git status` and `git diff --cached` in the
current directory, sends both to the LLM, and prints:

```
<title>

<description>
```

`description` is omitted if the model decides none is needed.

## Notes

- `Note:` it bases the message on **staged** files only — `git status` is
  included for context, but the diff sent to the model is `git diff --cached`.
  Unstaged changes won't be reflected.
- Output is copied to the clipboard via `pyperclip`, so `git commit` and paste
  works directly.
- Raises if the model doesn't return valid JSON (`{"title": ..., "description": ...}`).

## Requirements

- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` (see `.env.example`).
- Run from inside a git repository with something staged.
