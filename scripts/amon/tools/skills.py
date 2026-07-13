"""
skill-name/
├── SKILL.md          (required)
│   ├── YAML frontmatter: name, description
│   └── Markdown instructions
├── scripts/           (optional) — executable code
├── references/        (optional) — docs loaded on demand
└── assets/            (optional) — output templates/files
"""

import frontmatter
from pathlib import Path
from config import SKILLS_DIR


def builde_skill_catalog(skills_dir: Path = SKILLS_DIR) -> list[dict]:
    catalog = []
    for skill_path in skills_dir.glob("*/SKILL.md"):
        post = frontmatter.load(skill_path)
        catalog.append(
            {
                "name": post["name"],
                "description": post["description"],
                "path": str(skill_path),
            }
        )
    return catalog


skill_catalog = builde_skill_catalog()


def load_skill(skill_name: str, skills_dir: Path = SKILLS_DIR) -> str:
    path = skills_dir / skill_name
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
    allowed_names: list[str], full_catalog: list[dict] = skill_catalog
) -> list[dict]:
    return [s for s in full_catalog if s["name"] in allowed_names]
