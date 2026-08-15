"""Unit tests for QueryTrace / refusal_reason (no LLM / Chroma)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.query_trace import (
    QueryTrace,
    infer_outcome,
    infer_refusal_reason,
)


def test_infer_refusal_no_chunks():
    assert (
        infer_refusal_reason(
            retrieved_count=0,
            kept_count=0,
            no_context=True,
            answer="اطلاعات کافی",
        )
        == "no_chunks_retrieved"
    )


def test_infer_refusal_below_relevance():
    assert (
        infer_refusal_reason(
            retrieved_count=8,
            kept_count=0,
            no_context=True,
            answer="اطلاعات کافی",
        )
        == "below_relevance_threshold"
    )


def test_infer_refusal_llm_despite_chunks():
    assert (
        infer_refusal_reason(
            retrieved_count=5,
            kept_count=3,
            no_context=False,
            answer="اطلاعات کافی در منابع موجود نیست",
            llm_full_refuse=True,
        )
        == "llm_refused_despite_chunks"
    )


def test_infer_refusal_none_when_answered():
    assert (
        infer_refusal_reason(
            retrieved_count=5,
            kept_count=3,
            no_context=False,
            answer="طبق ماده …",
            llm_full_refuse=False,
        )
        is None
    )


def test_infer_outcome_low_confidence():
    assert (
        infer_outcome(
            no_context=False,
            llm_full_refuse=False,
            citation_confidence="partial",
        )
        == "low_confidence_answered"
    )


def test_query_trace_emit_jsonl(tmp_path: Path, monkeypatch):
    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("QUERY_TRACE_ENABLED", "true")
    monkeypatch.setenv("QUERY_TRACE_PATH", path.as_posix())
    # Re-import path binding — module reads env at import time; patch attribute
    import app.services.query_trace as qt

    monkeypatch.setattr(qt, "QUERY_TRACE_ENABLED", True)
    monkeypatch.setattr(qt, "QUERY_TRACE_PATH", path)

    trace = QueryTrace(query_id="qid-1")
    trace.set_queries(anonymized="سوال [NAME]", logged_preview="سوال [NAME]")
    trace.classify = {"domain": "مدنی", "confidence": 0.9, "cached": False}
    trace.generate["outcome"] = "refused"
    trace.generate["refusal_reason"] = "no_chunks_retrieved"
    payload = trace.emit()

    assert payload["event"] == "QUERY_TRACE"
    assert payload["query_id"] == "qid-1"
    assert payload["raw_query"] == "سوال [NAME]"
    assert "علی" not in json.dumps(payload, ensure_ascii=False)
    assert path.exists()
    line = path.read_text(encoding="utf-8").strip()
    data = json.loads(line)
    assert data["generate"]["refusal_reason"] == "no_chunks_retrieved"


def test_questions_jsonl_has_30():
    path = Path(__file__).resolve().parent.parent / "eval" / "questions.jsonl"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 30
    domains = {}
    for ln in lines:
        obj = json.loads(ln)
        assert "expected_outcome" in obj
        domains[obj["domain"]] = domains.get(obj["domain"], 0) + 1
    assert domains.get("civil", 0) >= 10
    assert domains.get("family", 0) >= 10
    assert domains.get("criminal", 0) >= 10
