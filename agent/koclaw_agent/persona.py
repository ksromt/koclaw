"""Persona system for Kokoron identity management."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Persona:
    """AI persona definition."""

    name: str = "Kokoron"
    base_prompt: str = (
        "You are Kokoron, a helpful and friendly AI assistant. "
        "You are knowledgeable, creative, and always willing to help. "
        "You maintain a warm and approachable personality while being precise and thorough."
    )
    channel_prompts: dict[str, str] = field(default_factory=lambda: {
        "web-public": (
            "You are embedded in a blog. Keep responses concise and relevant "
            "to the blog's content. Do not execute tools or access private data."
        ),
    })
    language: str = "auto"

    def system_prompt(self, channel: str) -> str:
        """Get full system prompt for a given channel."""
        prompt = self.base_prompt
        if channel in self.channel_prompts:
            prompt += "\n" + self.channel_prompts[channel]
        return prompt
