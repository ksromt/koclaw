"""Persona system for Kokoron identity management.

Loads the AI persona from a shared persona.yaml file (single source of truth)
or falls back to a hardcoded default when the file is absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Persona:
    """AI persona definition."""

    name: str = "Kokoron"
    base_prompt: str = ""
    channel_prompts: dict[str, dict] = field(default_factory=dict)
    language: str = "auto"
    traits: list[str] = field(default_factory=list)
    live2d: dict = field(default_factory=dict)
    voice: dict = field(default_factory=dict)

    def system_prompt(self, channel: str) -> str:
        """Get full system prompt for a given channel."""
        prompt = self.base_prompt
        if channel in self.channel_prompts:
            suffix = self.channel_prompts[channel].get("prompt_suffix", "")
            if suffix:
                prompt += "\n" + suffix
        return prompt

    @classmethod
    def from_yaml_file(cls, path: str | Path = "persona.yaml") -> Persona:
        """Load persona from a YAML file, falling back to default if not found."""
        path = Path(path)
        if not path.exists():
            return cls.default()
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return cls.default()
        return cls(
            name=data.get("name", "Kokoron"),
            base_prompt=data.get("base_prompt", ""),
            channel_prompts=data.get("channel_prompts", {}),
            language=data.get("language", "auto"),
            traits=data.get("traits", []),
            live2d=data.get("live2d", {}),
            voice=data.get("voice", {}),
        )

    @classmethod
    def default(cls) -> Persona:
        """Create a hardcoded fallback Kokoron persona."""
        return cls(
            name="Kokoron",
            base_prompt=(
                "You are Kokoron, a helpful and friendly AI assistant. "
                "You are knowledgeable, creative, and always willing to help. "
                "You maintain a warm and approachable personality while being precise and thorough."
            ),
        )
