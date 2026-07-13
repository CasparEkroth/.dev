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
import pathlib
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
