"""Load repository-local skills and render them as prior knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import yaml


FRONTMATTER = re.compile(
    r"\A---\s*\n(?P<yaml>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path


def read_skill(skill_path: str | Path) -> Skill:
    """Parse one SKILL.md without executing anything from the skill folder."""

    path = Path(skill_path)
    if not path.is_file():
        raise FileNotFoundError(f"Skill file does not exist: {path}")

    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(raw)
    if not match:
        raise ValueError(f"Skill has no valid YAML frontmatter: {path}")

    metadata = yaml.safe_load(match.group("yaml"))
    if not isinstance(metadata, dict):
        raise ValueError(f"Skill frontmatter must be a mapping: {path}")

    unexpected = set(metadata) - {"name", "description"}
    if unexpected:
        raise ValueError(
            f"Skill frontmatter contains unsupported keys {sorted(unexpected)}: "
            f"{path}"
        )

    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Skill name is missing: {path}")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Skill description is missing: {path}")

    return Skill(
        name=name.strip(),
        description=description.strip(),
        body=match.group("body").strip(),
        path=path.resolve(),
    )


def discover_skills(skill_root: str | Path) -> dict[str, Skill]:
    """Discover skill folders one level below ``skill_root``."""

    root = Path(skill_root)
    skills: dict[str, Skill] = {}
    if not root.exists():
        return skills

    for skill_file in sorted(root.glob("*/SKILL.md")):
        skill = read_skill(skill_file)
        if skill.name in skills:
            raise ValueError(
                f"Duplicate skill name {skill.name!r}: "
                f"{skills[skill.name].path} and {skill.path}"
            )
        skills[skill.name] = skill
    return skills


def render_skills(skills: list[Skill]) -> str:
    """Render selected skills for prompt injection."""

    if not skills:
        return ""

    rendered = [
        "The following skills are procedural prior knowledge, not factual "
        "sources. Apply only relevant instructions and independently verify "
        "all task-specific facts."
    ]
    for skill in skills:
        rendered.append(
            "\n".join(
                [
                    f'<skill name="{skill.name}">',
                    f"Description: {skill.description}",
                    skill.body,
                    "</skill>",
                ]
            )
        )
    return "\n\n".join(rendered)
