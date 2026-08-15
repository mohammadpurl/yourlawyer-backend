"""Structured per-query RAG traces (JSONL) for refusal diagnosis.

Extends the PIPELINE_TIMING idea: one JSON line per request with classify /
retrieve / rerank / generate decisions and an explicit ``refusal_reason``.

PII: callers must pass anonymized query text only (never raw user PII).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, CHROMA_COLLECTION, MIN_SOURCE_RELEVANCE_SCORE

logger = logging.getLogger("app.query_trace")

QUERY_TRACE_ENABLED = os.getenv("QUERY_TRACE_ENABLED", "true").lower() == "true"
QUERY_TRACE_PATH = Path(
    os.getenv(
        "QUERY_TRACE_PATH",
        (BASE_DIR / "storage" / "query_traces.jsonl").as_posix(),
    )
)


def _chunk_record(doc: Any, score: float | None = None) -> dict[str, Any]:
    meta = getattr(doc, "metadata", None) or {}
    text = getattr(doc, "page_content", "") or ""
    if text.startswith("passage: "):
        text = text[len("passage: ") :]
    chunk_id = str(meta.get("content_hash") or "")[:24] or None
    rec: dict[str, Any] = {
        "chunk_id": chunk_id,
        "source_doc": str(meta.get("law_name") or meta.get("source") or "")[:200],
        "domain_tag": meta.get("domain"),
        "subdomain_tag": meta.get("subdomain"),
        "text_preview": text[:160].replace("\n", " "),
    }
    if score is not None:
        rec["relevance_score"] = round(float(score), 6)
        rec["score"] = round(float(score), 6)
    return rec


def infer_refusal_reason(
    *,
    retrieved_count: int,
    kept_count: int,
    no_context: bool,
    answer: str | None,
    llm_full_refuse: bool = False,
    out_of_domain: bool = False,
    below_confidence: bool = False,
) -> str | None:
    """Map pipeline state → refusal_reason (or None if answered).

    Values: no_chunks_retrieved | below_relevance_threshold |
    below_confidence_threshold | out_of_domain | llm_refused_despite_chunks |
    empty_usable_context | None
    """
    if out_of_domain and (no_context or llm_full_refuse or below_confidence):
        return "out_of_domain"
    if not no_context and not llm_full_refuse and not below_confidence:
        return None
    if retrieved_count <= 0:
        return "no_chunks_retrieved"
    if kept_count <= 0:
        return "below_relevance_threshold"
    if below_confidence:
        return "below_confidence_threshold"
    if llm_full_refuse:
        return "llm_refused_despite_chunks"
    return "empty_usable_context"


def infer_outcome(
    *,
    no_context: bool,
    llm_full_refuse: bool,
    citation_confidence: str | None,
) -> str:
    if no_context or llm_full_refuse:
        return "refused"
    if citation_confidence in {"partial", "unverified"}:
        return "low_confidence_answered"
    return "answered"


class QueryTrace:
    """Accumulates one request's stage payloads; flush at end of RAG run."""

    def __init__(self, query_id: str):
        self.query_id = query_id
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.raw_query_logged: str | None = None  # anonymized preview only
        self.anonymized_query: str | None = None
        self.classify: dict[str, Any] = {}
        self.retrieve: dict[str, Any] = {
            "collection": CHROMA_COLLECTION,
            "domain_filter_applied": False,
            "top_k_requested": None,
            "chunks_returned": [],
        }
        self.rerank: dict[str, Any] = {
            "chunks_after_rerank": [],
            "min_relevance_threshold": MIN_SOURCE_RELEVANCE_SCORE,
            "chunks_dropped_below_threshold": 0,
        }
        self.generate: dict[str, Any] = {
            "model": None,
            "final_confidence_score": None,
            "confidence_threshold": None,
            "outcome": None,
            "refusal_reason": None,
        }
        self.timing_ms: dict[str, float] = {}
        self.extra: dict[str, Any] = {}

    def set_queries(self, *, anonymized: str, logged_preview: str) -> None:
        self.anonymized_query = anonymized
        # Never store raw PII — preview is already anonymized-for-logging
        self.raw_query_logged = logged_preview

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": "QUERY_TRACE",
            "query_id": self.query_id,
            "timestamp": self.timestamp,
            "raw_query": self.raw_query_logged,
            "anonymized_query": self.anonymized_query,
            "classify": self.classify,
            "retrieve": self.retrieve,
            "rerank": self.rerank,
            "generate": self.generate,
            "timing_ms": self.timing_ms,
            **self.extra,
        }

    def emit(self) -> dict[str, Any]:
        payload = self.as_dict()
        if not QUERY_TRACE_ENABLED:
            return payload
        try:
            line = json.dumps(payload, ensure_ascii=False)
            logger.info("QUERY_TRACE %s", line)
            QUERY_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(QUERY_TRACE_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            logger.exception("Failed to write QUERY_TRACE")
        return payload
