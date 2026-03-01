"""Parser for ClawHub SKILL.md format."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


@dataclass
class SkillDefinition:
    """Parsed representation of a SKILL.md file."""
    name: str
    description: str = ""
    version: str = "0.0.0"
    instructions: str = ""
    required_env: list[str] = field(default_factory=list)
    required_bins: list[str] = field(default_factory=list)
    user_invocable: bool = False
    install_script: str = ""
    emoji: str = ""
    homepage: str = ""


def parse_skill_md(content: str) -> SkillDefinition:
    """Parse a SKILL.md string into a SkillDefinition."""
    frontmatter_match = re.match(
        r'^---\s*\n(.*?)\n---\s*\n?(.*)',
        content,
        re.DOTALL
    )

    if not frontmatter_match:
        return SkillDefinition(name="unknown", instructions=content.strip())

    yaml_str = frontmatter_match.group(1)
    body = frontmatter_match.group(2).strip()

    try:
        meta = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError:
        return SkillDefinition(name="unknown", instructions=body)

    openclaw_meta = meta.get("metadata", {}).get("openclaw", {})

    return SkillDefinition(
        name=meta.get("name", "unknown"),
        description=meta.get("description", ""),
        version=str(meta.get("version", "0.0.0")),
        instructions=body,
        required_env=openclaw_meta.get("env", []),
        required_bins=openclaw_meta.get("bins", []),
        user_invocable=meta.get("user-invocable", False),
        install_script=meta.get("install", ""),
        emoji=openclaw_meta.get("emoji", ""),
        homepage=openclaw_meta.get("homepage", ""),
    )
