"""Tests for citation grounding validation."""

from app.services.citation_validator import (
    extract_citations,
    validate_citations,
    citation_accuracy_score,
)
from app.services.response_warnings import prepend_strong_warning


def test_extract_citations_variants():
    from app.services.citation_validator import _CITATION_RE, _canonical_form

    text = "طبق ماده ۱۰ و ماده 12 و ماده دهم و تبصره ۲ ماده ۱۵ و اصل ۵۶"
    cited = extract_citations(text)
    assert any("ماده ۱۰" in c or "ماده 10" in c for c in cited)
    assert any("ماده 12" in c or "ماده ۱۲" in c for c in cited)
    assert any("تبصره" in c for c in cited)
    assert any("اصل" in c for c in cited)
    # Ordinal form normalizes to the same canonical article number
    m = _CITATION_RE.search("ماده دهم")
    assert m is not None
    assert _canonical_form(m) == "ماده 10"


def test_verified_citation_in_context():
    response = "بر اساس ماده ۱۰ قانون مدنی، اهلیت لازم است."
    chunks = ["در ماده ۱۰ قانون مدنی آمده است که اهلیت شرط است."]
    result = validate_citations(response, chunks)
    assert result.confidence_flag == "verified"
    assert result.is_valid
    assert not result.unverified_citations
    assert citation_accuracy_score(result) == 1.0


def test_unverified_citation_flagged():
    response = "طبق ماده ۹۹۹ این کار ممنوع است."
    chunks = ["در ماده ۱۰ قانون مدنی اهلیت شرط است."]
    result = validate_citations(response, chunks)
    assert result.confidence_flag in ("unverified", "partial")
    assert result.unverified_citations
    assert "ماده ۹۹۹" in result.unverified_citations[0] or any(
        "۹۹۹" in c or "999" in c for c in result.unverified_citations
    )


def test_mixed_citations_partial():
    response = "ماده ۱۰ درست است ولی ماده ۹۹۹ در منابع نیست."
    chunks = ["متن مربوط به ماده ۱۰ قانون مدنی."]
    result = validate_citations(response, chunks)
    assert result.confidence_flag == "partial"
    assert result.cited_articles
    assert result.unverified_citations
    score = citation_accuracy_score(result)
    assert 0 < score < 1


def test_warning_prepend():
    body = "پاسخ نمونه"
    out = prepend_strong_warning(body, reason="citation_unverified")
    assert out.startswith("⚠️")
    assert "پاسخ نمونه" in out
