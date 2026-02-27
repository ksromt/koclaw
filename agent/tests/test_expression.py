"""Tests for expression extraction system."""

from koclaw_agent.expression import extract_expressions


def test_extract_single_expression():
    result = extract_expressions("I'm so happy! [joy]")
    assert result.expressions == ["joy"]
    assert "[joy]" not in result.clean_text
    assert "happy" in result.clean_text


def test_extract_multiple_expressions():
    result = extract_expressions("[thinking] Let me consider... [surprise] Oh!")
    assert result.expressions == ["thinking", "surprise"]
    assert "Let me consider..." in result.clean_text
    assert "Oh!" in result.clean_text


def test_no_expressions():
    result = extract_expressions("Hello, how are you?")
    assert result.expressions == []
    assert result.clean_text == "Hello, how are you?"


def test_unknown_expression_left_in_place():
    result = extract_expressions("[happy] Hello [unknown_emotion]")
    # "happy" is not in KNOWN_EXPRESSIONS, but "joy" is
    assert "happy" not in result.expressions
    assert "unknown_emotion" not in result.expressions
    assert "[unknown_emotion]" in result.clean_text


def test_all_known_expressions():
    text = "[joy] [anger] [sadness] [surprise] [thinking] [neutral]"
    result = extract_expressions(text)
    assert result.expressions == ["joy", "anger", "sadness", "surprise", "thinking", "neutral"]
    assert result.clean_text == ""


def test_expressions_case_insensitive():
    result = extract_expressions("[JOY] hello [Thinking]")
    assert "joy" in result.expressions
    assert "thinking" in result.expressions


def test_empty_text():
    result = extract_expressions("")
    assert result.expressions == []
    assert result.clean_text == ""
