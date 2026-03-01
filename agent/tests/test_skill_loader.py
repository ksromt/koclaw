"""Tests for skill loader."""
from pathlib import Path
import pytest
from koclaw_agent.mcp_host.skill_loader import SkillLoader


@pytest.fixture
def skill_dir(tmp_path):
    s1 = tmp_path / "web-search"
    s1.mkdir()
    (s1 / "SKILL.md").write_text(
        "---\nname: web-search\ndescription: Search the web\nversion: 1.0.0\n"
        "user-invocable: true\n---\nSearch using ddg-search tool.\n"
    )
    s2 = tmp_path / "code-review"
    s2.mkdir()
    (s2 / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review code quality\nversion: 0.5.0\n"
        "---\nAnalyze the code and provide feedback.\n"
    )
    s3 = tmp_path / "random-dir"
    s3.mkdir()
    (s3 / "README.md").write_text("Not a skill")
    return tmp_path


def test_load_skills_from_directory(skill_dir):
    loader = SkillLoader()
    skills = loader.load_from_directory(skill_dir)
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert "web-search" in names
    assert "code-review" in names


def test_load_skills_empty_dir(tmp_path):
    loader = SkillLoader()
    assert loader.load_from_directory(tmp_path) == []


def test_load_skills_nonexistent_dir():
    loader = SkillLoader()
    assert loader.load_from_directory(Path("/nonexistent/path")) == []


def test_get_invocable_skills(skill_dir):
    loader = SkillLoader()
    loader.load_from_directory(skill_dir)
    invocable = loader.get_invocable_skills()
    assert len(invocable) == 1
    assert invocable[0].name == "web-search"


def test_build_skills_prompt(skill_dir):
    loader = SkillLoader()
    loader.load_from_directory(skill_dir)
    prompt = loader.build_skills_prompt()
    assert "web-search" in prompt
    assert "code-review" in prompt
    assert "Search using ddg-search tool" in prompt
