"""Tests for tool surface validation — from test plan section 'Tool Surface Validation'."""

from src.tools.protocol import (
    validate_text_length,
    MAX_MESSAGE_LENGTH,
    MAX_SUBJECT_LENGTH,
)


def test_message_length_limit():
    """2001 chars → error."""
    ok = validate_text_length("a" * 2000, "body", MAX_MESSAGE_LENGTH)
    assert ok is None

    err = validate_text_length("a" * 2001, "body", MAX_MESSAGE_LENGTH)
    assert err is not None
    assert "2001" in err


def test_subject_length_limit():
    """501 chars → error."""
    ok = validate_text_length("a" * 500, "subject", MAX_SUBJECT_LENGTH)
    assert ok is None

    err = validate_text_length("a" * 501, "subject", MAX_SUBJECT_LENGTH)
    assert err is not None
    assert "501" in err


def test_empty_string_is_valid():
    assert validate_text_length("", "body", MAX_MESSAGE_LENGTH) is None


def test_exact_limit_is_valid():
    assert validate_text_length("a" * MAX_MESSAGE_LENGTH, "body", MAX_MESSAGE_LENGTH) is None
    assert validate_text_length("a" * MAX_SUBJECT_LENGTH, "subject", MAX_SUBJECT_LENGTH) is None
