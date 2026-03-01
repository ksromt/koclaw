"""Tests for SKILL.md parser."""
from koclaw_agent.mcp_host.skill_parser import SkillDefinition, parse_skill_md

SAMPLE_SKILL_MD = '''---
name: web-search
description: Search the web using DuckDuckGo
version: 1.2.0
metadata:
  openclaw:
    env:
      - DDG_API_KEY
    bins:
      - curl
    emoji: "\U0001f50d"
    homepage: https://github.com/example/web-search-skill
user-invocable: true
---

## Instructions

When the user asks you to search the web:

1. Use the `ddg-search` MCP tool with the user's query
2. Summarize the top 3 results
3. Include source URLs

Keep summaries concise (2-3 sentences per result).
'''


def test_parse_skill_md_basic():
    skill = parse_skill_md(SAMPLE_SKILL_MD)
    assert skill.name == "web-search"
    assert skill.description == "Search the web using DuckDuckGo"
    assert skill.version == "1.2.0"
    assert "ddg-search" in skill.instructions
    assert skill.user_invocable is True


def test_parse_skill_md_env_vars():
    skill = parse_skill_md(SAMPLE_SKILL_MD)
    assert "DDG_API_KEY" in skill.required_env


def test_parse_skill_md_bins():
    skill = parse_skill_md(SAMPLE_SKILL_MD)
    assert "curl" in skill.required_bins


def test_parse_skill_md_minimal():
    md = "---\nname: simple\ndescription: A simple skill\n---\nDo the thing."
    skill = parse_skill_md(md)
    assert skill.name == "simple"
    assert "Do the thing" in skill.instructions


def test_parse_skill_md_no_frontmatter():
    skill = parse_skill_md("Just some instructions without frontmatter.")
    assert skill.name == "unknown"
    assert "Just some instructions" in skill.instructions
