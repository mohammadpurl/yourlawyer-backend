"""PDF extract quality gates (no Chroma / no network)."""

from app.services.ingestion import (
    assess_extracted_text_quality,
    normalize_persian_pdf_text,
)


def test_normalize_collapses_presentation_forms():
    # Isolated/medial presentation forms commonly seen in bad PDF extracts
    sample = "ﻗﺎﻧﻮن ﻛﺎر"
    out = normalize_persian_pdf_text(sample)
    assert "قانون" in out
    assert "کار" in out or "كار" in out
    q = assess_extracted_text_quality(out)
    assert q["presentation_forms"] == 0
    assert q["persian_letters"] >= 7


def test_reject_literal_unicode_escapes():
    garbage = " ".join(f"/u06{i:02x}" for i in range(40))
    q = assess_extracted_text_quality(garbage * 3)
    assert not q["ok"]
    assert "literal_unicode_escapes" in q["reasons"]


def test_reject_empty_scan():
    q = assess_extracted_text_quality("   \n  ")
    assert not q["ok"]
    assert "empty_or_scan_pdf" in q["reasons"]


def test_accept_clean_persian_law():
    text = "ماده 1 ـ کلیه کارفرمایان و کارگران مکلف به تبعیت از این قانون کار هستند.\n" * 5
    q = assess_extracted_text_quality(text)
    assert q["ok"]
    assert q["persian_letters"] > 40
