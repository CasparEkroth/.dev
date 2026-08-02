# Reference: skill format

Source: `scripts/amon/tools/skills.py`

## Directory

```text
<skill_root>/
  SKILL.md          # required for catalog entry
  **/*              # optional resources listed on load
```

Catalog path stored for the agent is `str(skill_path.parent)` (the skill directory).

## SKILL.md frontmatter

Parsed with `frontmatter.load`.

| Key | Type | Default if missing |
|-----|------|--------------------|
| `name` | string | parent directory name |
| `description` | string | `""` |

Body: markdown instructions (string content after frontmatter).

## `skill://` URI

Pattern: `skill://` + path/glob

| Prefix after scheme | Resolution |
|---------------------|------------|
| `~…` | `os.path.expanduser` |
| `/…` | absolute filesystem path |
| other | `base_dir / raw` (base_dir default = cwd) |

Multiple patterns dedupe by resolved path.

## Catalog entry shape

```json
{
  "name": "python-validate",
  "description": "Use whenever Python code…",
  "path": "/Users/you/.amon/skills/python-validate"
}
```

## `load_skill` output shape

Concatenation of:

1. `SKILL.md` markdown body (no frontmatter)
2. literal `resources:\n`
3. relative (to cwd) paths of non-`SKILL.md` files under the skill tree, one per line

## Agent field

```json
"allowed_skills": ["skill://~/.amon/skills/*/SKILL.md"]
```
