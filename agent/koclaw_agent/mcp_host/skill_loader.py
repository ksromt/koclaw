"""Load and manage SKILL.md definitions from local directories."""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from .skill_parser import SkillDefinition, parse_skill_md


class SkillLoader:
    """Loads SKILL.md files from directories and provides them to the Agent."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def load_from_directory(self, directory: Path) -> list[SkillDefinition]:
        loaded = []
        if not directory.is_dir():
            return loaded
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")
                skill = parse_skill_md(content)
                self._skills[skill.name] = skill
                loaded.append(skill)
            except Exception:
                logger.exception("Failed to load skill from %s", skill_file)
        return loaded

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def get_invocable_skills(self) -> list[SkillDefinition]:
        return [s for s in self._skills.values() if s.user_invocable]

    def get_all_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def build_skills_prompt(self) -> str:
        skills = self.get_all_skills()
        if not skills:
            return ""
        lines = ["", "## Available Skills", "",
                 "The following skills provide specialized instructions:", ""]
        for skill in skills:
            emoji = f"{skill.emoji} " if skill.emoji else ""
            lines.append(f"### {emoji}{skill.name}")
            lines.append(f"*{skill.description}*")
            lines.append("")
            lines.append(skill.instructions)
            lines.append("")
        return "\n".join(lines)
