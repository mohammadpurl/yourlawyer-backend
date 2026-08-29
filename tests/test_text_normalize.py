"""Unit tests for shared Persian text normalization."""

from app.services.text_normalize import normalize_persian_text


def test_arabic_kaf_yeh_aligns_with_persian():
    assert normalize_persian_text("كتاب") == normalize_persian_text("کتاب")


def test_normalize_empty():
    assert normalize_persian_text("") == ""
    assert normalize_persian_text(None) == ""  # type: ignore[arg-type]
