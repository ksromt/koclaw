"""Extract emotion expressions from LLM output for Live2D animation.

The LLM is prompted to emit bracketed emotion tags like [joy], [anger], etc.
This module strips those tags and returns them separately so the frontend
can drive Live2D expression changes in sync with the text response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EXPRESSION_PATTERN = re.compile(r"\[(\w+)\]")

# Known expressions — must match persona.yaml live2d.expressions keys
KNOWN_EXPRESSIONS = {"joy", "anger", "sadness", "surprise", "thinking", "neutral"}


@dataclass
class ExpressionResult:
    """Result of expression extraction."""

    clean_text: str  # Text with expression tags removed
    expressions: list[str]  # Extracted expression names in order


def extract_expressions(text: str) -> ExpressionResult:
    """Extract [emotion] tags from text and return cleaned text + expressions list.

    Only tags matching KNOWN_EXPRESSIONS are extracted; unknown bracketed words
    are left in place so they don't break the text.
    """
    expressions: list[str] = []

    def _replace(match: re.Match) -> str:
        expr = match.group(1).lower()
        if expr in KNOWN_EXPRESSIONS:
            expressions.append(expr)
            return ""
        return match.group(0)  # leave unknown tags in place

    clean_text = EXPRESSION_PATTERN.sub(_replace, text).strip()
    # Collapse double spaces left by removal
    clean_text = re.sub(r"  +", " ", clean_text)

    return ExpressionResult(clean_text=clean_text, expressions=expressions)
