"""Re-ranking service for improving RAG retrieval accuracy.

ROOT CAUSE (2026-08 audit — see ``diagnostics/audit_reranker.py``):
  The previous default ``cross-encoder/ms-marco-MiniLM-L-6-v2`` is an *English*
  MS MARCO CrossEncoder. On Persian legal query/passage pairs it still emits
  large positive logits for both relevant and irrelevant chunks (e.g. 9.16 vs
  8.35). After sigmoid that collapses to ~0.999 / ~0.999 (delta << 0.05), so
  ``MIN_SOURCE_RELEVANCE_SCORE`` cannot filter noise — the stage looked like a
  real rerank but produced no usable discrimination.

  Fixes:
  1. Default model → multilingual ``mmarco-mMiniLMv2-L12-H384-v1``.
  2. Strip E5 ``passage:`` / ``query:`` prefixes before CE scoring.
  3. When CE score spread inside a batch is < RERANKER_COLLAPSE_SPREAD, blend
     heavily with Persian keyword relevance (hybrid) so ranking/filter still
     works even if HF falls back to the English MiniLM checkpoint.
"""

from __future__ import annotations

import logging
import math
import os
from typing import List, Optional, Tuple

from langchain_core.documents import Document

from app.core.config import (
    RERANKER_ENABLED,
    RERANKER_MODEL,
    MIN_SOURCE_RELEVANCE_SCORE,
)

logger = logging.getLogger(__name__)

_reranker_model = None
_reranker_loading_attempted = False
_reranker_loaded_name: str | None = None

# If max(ce)-min(ce) within a scored batch is below this, treat CE as collapsed.
RERANKER_COLLAPSE_SPREAD = float(os.getenv("RERANKER_COLLAPSE_SPREAD", "0.05"))
# Blend weights when collapsed vs healthy: (cross_encoder, keyword)
_RERANK_BLEND_COLLAPSED = (
    float(os.getenv("RERANKER_BLEND_CE_COLLAPSED", "0.25")),
    float(os.getenv("RERANKER_BLEND_KW_COLLAPSED", "0.75")),
)
_RERANK_BLEND_HEALTHY = (
    float(os.getenv("RERANKER_BLEND_CE_HEALTHY", "0.85")),
    float(os.getenv("RERANKER_BLEND_KW_HEALTHY", "0.15")),
)


def get_reranker_model():
    """Get or load reranker model."""
    global _reranker_model, _reranker_loading_attempted, _reranker_loaded_name

    if not RERANKER_ENABLED:
        return None

    if _reranker_model is None and not _reranker_loading_attempted:
        _reranker_loading_attempted = True
        try:
            from sentence_transformers import CrossEncoder

            hf_timeout = int(os.getenv("HF_TIMEOUT", "300"))
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(hf_timeout))

            logger.info(
                "Loading reranker model: %s (timeout: %ss)",
                RERANKER_MODEL,
                hf_timeout,
            )
            # activation_fn=None → raw logits; we apply sigmoid ourselves.
            _reranker_model = CrossEncoder(RERANKER_MODEL, activation_fn=None)
            _reranker_loaded_name = RERANKER_MODEL
            logger.info("Reranker model '%s' loaded successfully", RERANKER_MODEL)

        except Exception as e:
            logger.warning(
                "Could not load reranker model '%s': %s. "
                "Re-ranking will use keyword scores only. "
                "HF_TIMEOUT=%s",
                RERANKER_MODEL,
                e,
                os.getenv("HF_TIMEOUT", "300"),
            )
            return None

    return _reranker_model


def _sigmoid(x: float) -> float:
    # numerically stable
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _strip_embed_prefix(text: str) -> str:
    """Remove E5 passage/query prefixes that confuse CrossEncoder input."""
    t = text or ""
    for prefix in ("passage: ", "query: ", "passage:", "query:"):
        if t.startswith(prefix):
            return t[len(prefix) :].lstrip()
    return t


def _keyword_relevance(query: str, doc: Document) -> float:
    """Cheap 0..1 fallback / hybrid signal for Persian legal text."""
    q_tokens = [t for t in (query or "").replace("\u200c", " ").split() if len(t) > 1]
    if not q_tokens:
        return 0.0
    meta = getattr(doc, "metadata", None) or {}
    blob = " ".join(
        [
            _strip_embed_prefix(getattr(doc, "page_content", "") or ""),
            str(meta.get("law_name") or ""),
            str(meta.get("source") or ""),
            str(meta.get("domain") or ""),
            str(meta.get("subdomain") or ""),
        ]
    )
    hits = sum(1 for t in q_tokens if t in blob)
    law = str(meta.get("law_name") or "")
    boost = 0.25 if any(len(t) > 2 and t in law for t in q_tokens) else 0.0
    # Extra boost for distinctive multi-token legal phrases present in blob
    q_norm = (query or "").replace("\u200c", " ")
    for phrase in ("ضمان قهری", "قانون مدنی", "مهریه", "طلاق", "قانون کار"):
        if phrase in q_norm and phrase in blob:
            boost += 0.2
    return min(1.0, hits / max(1, len(q_tokens)) + boost)


def score_documents(
    query: str,
    documents: List[Document],
) -> List[Tuple[Document, float]]:
    """Return (doc, score∈[0,1]) pairs sorted descending by relevance."""
    if not documents:
        return []

    kw_scores = [_keyword_relevance(query, d) for d in documents]

    model = get_reranker_model()
    if not model:
        scored = list(zip(documents, kw_scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    try:
        pairs = [[query, _strip_embed_prefix(doc.page_content)] for doc in documents]
        raw_scores = model.predict(pairs)
        ce_scores = [_sigmoid(float(s)) for s in raw_scores]
        spread = (max(ce_scores) - min(ce_scores)) if ce_scores else 0.0

        if spread < RERANKER_COLLAPSE_SPREAD:
            ce_w, kw_w = _RERANK_BLEND_COLLAPSED
            logger.warning(
                "Reranker CE collapse: spread=%.5f model=%s → hybrid "
                "ce=%.2f kw=%.2f (English MiniLM on Persian saturates; "
                "see diagnostics/audit_reranker.py)",
                spread,
                _reranker_loaded_name or RERANKER_MODEL,
                ce_w,
                kw_w,
            )
        else:
            ce_w, kw_w = _RERANK_BLEND_HEALTHY

        scored_docs = [
            (doc, float(ce_w * ce + kw_w * kw))
            for doc, ce, kw in zip(documents, ce_scores, kw_scores)
        ]
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        return scored_docs
    except Exception as e:
        logger.warning("Error during re-ranking: %s. Using keyword scores.", e)
        scored = list(zip(documents, kw_scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


def filter_by_min_score(
    scored: List[Tuple[Document, float]],
    min_score: float | None = None,
) -> List[Document]:
    """Keep only documents at/above relevance threshold."""
    threshold = MIN_SOURCE_RELEVANCE_SCORE if min_score is None else float(min_score)
    kept_pairs = [(doc, score) for doc, score in scored if score >= threshold]
    kept = [doc for doc, _ in kept_pairs]
    dropped = len(scored) - len(kept)
    top_scores = [round(s, 3) for _, s in scored[:5]]
    logger.info(
        "score_filter retrieved=%s kept=%s dropped=%s threshold=%.3f top_scores=%s",
        len(scored),
        len(kept),
        dropped,
        threshold,
        top_scores,
    )
    if scored and not kept:
        logger.warning(
            "score_filter emptied context | retrieved=%s threshold=%.3f "
            "top_scores=%s (lower MIN_SOURCE_RELEVANCE_SCORE or disable reranker)",
            len(scored),
            threshold,
            top_scores,
        )
    return kept


def rerank_documents(
    query: str,
    documents: List[Document],
    top_k: Optional[int] = None,
    min_score: float | None = None,
) -> List[Document]:
    """
    Re-rank documents and drop those below MIN_SOURCE_RELEVANCE_SCORE.

    Returns may be empty — callers should treat that as no usable context.
    """
    if not documents:
        return documents

    scored = score_documents(query, documents)
    kept = filter_by_min_score(scored, min_score=min_score)
    if top_k is not None:
        kept = kept[:top_k]

    logger.info(
        "Re-ranked retrieved=%s kept=%s after score filter (top_k=%s)",
        len(documents),
        len(kept),
        top_k,
    )
    return kept
