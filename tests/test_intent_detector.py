"""Unit tests for pre-RAG intent detection (mocked LLM; no OpenAI/Chroma)."""

from __future__ import annotations

import pytest

from app.services.canned_responses import CANNED_RESPONSES, get_canned_response
from app.services.intent_detector import (
    IntentResult,
    detect_intent,
    _legal_question_fallback,
)


@pytest.fixture(autouse=True)
def _no_redis_cache(monkeypatch):
    monkeypatch.setattr(
        "app.services.intent_detector.cache_get", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "app.services.intent_detector.cache_set", lambda *a, **k: None
    )


def test_canned_meta_mentions_no_drafting():
    text = get_canned_response("meta_capability")
    assert "شکواییه" in text or "دادخواست" in text
    assert "فراهم نیست" in text or "در حال توسعه" in text
    assert "استناد" in text or "منابع" in text


def test_canned_all_intents_have_templates():
    for key in ("meta_capability", "greeting_chitchat", "out_of_scope"):
        assert key in CANNED_RESPONSES
        assert len(CANNED_RESPONSES[key]) > 20


def test_shakyaye_example_is_meta_capability(monkeypatch):
    monkeypatch.setattr(
        "app.services.intent_detector.ENABLE_INTENT_DETECTION", True
    )
    monkeypatch.setattr(
        "app.services.intent_detector.OPENAI_API_KEY", "sk-test"
    )

    def fake_llm(query: str) -> IntentResult:
        assert "شکواییه" in query
        return IntentResult(
            intent="meta_capability",
            confidence=0.95,
            raw_model_response='{"intent":"meta_capability","confidence":0.95}',
        )

    monkeypatch.setattr(
        "app.services.intent_detector._llm_detect", fake_llm
    )
    result = detect_intent("آیا تو می‌تونی شکواییه تهیه کنی؟")
    assert result.intent == "meta_capability"
    assert result.confidence >= 0.9


@pytest.mark.parametrize(
    "label",
    ["legal_question", "meta_capability", "greeting_chitchat", "out_of_scope"],
)
def test_detect_intent_labels(monkeypatch, label):
    monkeypatch.setattr(
        "app.services.intent_detector.ENABLE_INTENT_DETECTION", True
    )
    monkeypatch.setattr(
        "app.services.intent_detector.OPENAI_API_KEY", "sk-test"
    )
    monkeypatch.setattr(
        "app.services.intent_detector._llm_detect",
        lambda q: IntentResult(
            intent=label, confidence=0.8, raw_model_response="{}"
        ),
    )
    assert detect_intent("نمونه").intent == label


def test_fail_open_on_llm_exception(monkeypatch):
    monkeypatch.setattr(
        "app.services.intent_detector.ENABLE_INTENT_DETECTION", True
    )
    monkeypatch.setattr(
        "app.services.intent_detector.OPENAI_API_KEY", "sk-test"
    )

    def boom(_q: str):
        raise RuntimeError("openai down")

    monkeypatch.setattr("app.services.intent_detector._llm_detect", boom)
    result = detect_intent("مهریه عندالمطالبه چیست؟")
    assert result.intent == "legal_question"


def test_fail_open_unknown_label(monkeypatch):
    monkeypatch.setattr(
        "app.services.intent_detector.ENABLE_INTENT_DETECTION", True
    )
    monkeypatch.setattr(
        "app.services.intent_detector.OPENAI_API_KEY", "sk-test"
    )

    class FakeResp:
        content = '{"intent":"totally_unknown","confidence":0.9}'

    class FakeLLM:
        def invoke(self, _messages):
            return FakeResp()

    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kwargs: FakeLLM())
    result = detect_intent("سلام تست")
    assert result.intent == "legal_question"


def test_feature_flag_off_always_legal(monkeypatch):
    monkeypatch.setattr(
        "app.services.intent_detector.ENABLE_INTENT_DETECTION", False
    )

    def should_not_run(_q: str):
        raise AssertionError("LLM must not be called when flag off")

    monkeypatch.setattr(
        "app.services.intent_detector._llm_detect", should_not_run
    )
    result = detect_intent("آیا تو می‌تونی شکواییه تهیه کنی؟")
    assert result.intent == "legal_question"
    assert result.raw_model_response == "feature_flag_off"


def test_legal_question_fallback_helper():
    r = _legal_question_fallback(raw="x", confidence=0.1)
    assert r.intent == "legal_question"
