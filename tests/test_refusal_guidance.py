"""Unit tests for refusal messages + level-3 guidance gates (no OpenAI)."""

from app.services.refusal_guidance import (
    REFUSAL_USER_MESSAGES,
    _sanitize_guidance_text,
    format_refusal_user_message,
    generate_general_guidance,
    should_offer_general_guidance,
)
from app.services.query_trace import infer_outcome


def test_all_known_refusal_reasons_have_messages():
    known = {
        "no_chunks_retrieved",
        "below_relevance_threshold",
        "out_of_domain",
        "below_confidence_threshold",
        "llm_refused_despite_chunks",
        "empty_usable_context",
        "pipeline_error",
    }
    assert known <= set(REFUSAL_USER_MESSAGES.keys())


def test_format_refusal_includes_domain_hint():
    msg = format_refusal_user_message(
        "below_relevance_threshold",
        taxonomy_domain="کار_و_تامین_اجتماعی",
    )
    assert "حقوق کار و تأمین اجتماعی" in msg
    assert "مرتبط و دقیق" in msg


def test_format_refusal_unmapped_logs_fallback(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        msg = format_refusal_user_message("totally_unknown_reason_xyz")
    assert "قابل‌اتکا" in msg or "مستند" in msg
    assert any("Unmapped refusal_reason" in r.message for r in caplog.records)


def test_should_offer_guidance_requires_flag_and_confidence(monkeypatch):
    import app.services.refusal_guidance as rg

    monkeypatch.setattr(rg, "ENABLE_GENERAL_GUIDANCE_FALLBACK", False)
    assert not should_offer_general_guidance(
        refusal_reason="below_relevance_threshold",
        taxonomy_domain="کار_و_تامین_اجتماعی",
        taxonomy_confidence=0.9,
    )

    monkeypatch.setattr(rg, "ENABLE_GENERAL_GUIDANCE_FALLBACK", True)
    monkeypatch.setattr(rg, "GENERAL_GUIDANCE_MIN_CLASSIFY_CONFIDENCE", 0.6)
    assert should_offer_general_guidance(
        refusal_reason="below_relevance_threshold",
        taxonomy_domain="کار_و_تامین_اجتماعی",
        taxonomy_confidence=0.85,
    )
    assert not should_offer_general_guidance(
        refusal_reason="below_relevance_threshold",
        taxonomy_domain="کار_و_تامین_اجتماعی",
        taxonomy_confidence=0.4,
    )
    assert not should_offer_general_guidance(
        refusal_reason="out_of_domain",
        taxonomy_domain="کار_و_تامین_اجتماعی",
        taxonomy_confidence=0.9,
    )
    assert not should_offer_general_guidance(
        refusal_reason="no_chunks_retrieved",
        taxonomy_domain="نامشخص",
        taxonomy_confidence=0.9,
    )


def test_sanitize_rejects_article_leak():
    bad = "طبق قانون ماده ۲۲ شما مستحق بیمه هستید."
    out = _sanitize_guidance_text(bad, "کار_و_تامین_اجتماعی")
    assert "ماده" not in out or "ماده ۲۲" not in out
    assert "حقوق کار" in out
    assert "راهنمایی کلی" in out or "وکیل" in out


def test_static_general_guidance_no_articles():
    text = generate_general_guidance(
        query="حادثه در دوره آزمایشی",
        taxonomy_domain="کار_و_تامین_اجتماعی",
        user=None,
        db=None,
    )
    assert "ماده" not in text
    assert "قانون کار" in text or "کار" in text
    assert "وکیل" in text or "رسمی" in text


def test_infer_outcome_general_guidance():
    assert (
        infer_outcome(
            no_context=True,
            llm_full_refuse=False,
            citation_confidence=None,
            response_type="general_guidance",
        )
        == "general_guidance"
    )
    assert (
        infer_outcome(
            no_context=True,
            llm_full_refuse=False,
            citation_confidence=None,
        )
        == "refused"
    )
