"""Skill loading via skill:// URIs and catalog builder."""

from glob import glob
import os
import frontmatter
from pathlib import Path

SCHEME = "skill://"


def _strip_scheme(resource: str) -> str:
    if not resource.startswith(SCHEME):
        raise ValueError("Not a skill:// resource")
    return resource[len(SCHEME) :]


def resolve_pattern(resource: str, base_dir: Path | str | None) -> list[Path]:
    raw = _strip_scheme(resource)
    base_dir = Path(base_dir) if base_dir else Path.cwd()

    if raw.startswith("~"):
        pattern = os.path.expanduser(raw)
    elif raw.startswith("/"):
        pattern = raw
    else:
        pattern = str(base_dir / raw)

    matches = glob(pattern, recursive=True)
    return [Path(m).resolve() for m in matches if Path(m).is_file()]


def resolve_resources(
    resources: list[str], base_dir: Path | str | None = None
) -> list[Path]:
    seen: dict[Path, None] = {}
    for resource in resources:
        for path in resolve_pattern(resource, base_dir=base_dir):
            seen.setdefault(path, None)

    return list(seen.keys())


def build_skill_catalog(
    resources: list[str] | None = None,
    base_dir: Path | str | None = None,
) -> list[dict]:
    """
    Build a catalog of skills from skill:// URI patterns.

    Examples:
        skill://.amon/skills/*/SKILL.md   -> relative to base_dir
        skill://~/.amon/skills/*/SKILL.md -> relative to home
        skill:///abs/path/skills/*/SKILL.md -> absolute (triple slash)
    """
    if resources is None:
        return []
    paths = resolve_resources(resources, base_dir=base_dir)
    catalog = []
    for skill_path in paths:
        post = frontmatter.load(skill_path)
        catalog.append(
            {
                "name": post.get("name", skill_path.parent.name),
                "description": post.get("description", ""),
                "path": str(skill_path.parent),
            }
        )
    return catalog


def load_skill(skill_path: Path | str) -> str:
    path = Path(skill_path)
    cwd = Path.cwd()
    content: str = ""
    resources: str = ""
    for p in path.rglob("*"):
        if p.name == "SKILL.md":
            post = frontmatter.load(p)
            content = post.content
        else:
            try:
                rel = p.relative_to(cwd)
            except ValueError:
                rel = p
            resources += f"{rel}\n"
    return content + "resources:\n" + resources


def catalog_for_agent(
    resources: list[str], base_dir: Path | str | None = None
) -> list[dict]:
    return build_skill_catalog(resources=resources, base_dir=base_dir)
