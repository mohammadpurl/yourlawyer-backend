"""Re-ranking service for improving RAG retrieval accuracy."""

from __future__ import annotations

import logging
import math
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


def get_reranker_model():
    """Get or load reranker model."""
    global _reranker_model, _reranker_loading_attempted

    if not RERANKER_ENABLED:
        return None

    if _reranker_model is None and not _reranker_loading_attempted:
        _reranker_loading_attempted = True
        try:
            import os
            from sentence_transformers import CrossEncoder

            hf_timeout = int(os.getenv("HF_TIMEOUT", "300"))
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(hf_timeout))

            logger.info(
                "Loading reranker model: %s (timeout: %ss)",
                RERANKER_MODEL,
                hf_timeout,
            )
            _reranker_model = CrossEncoder(RERANKER_MODEL)
            logger.info("Reranker model '%s' loaded successfully", RERANKER_MODEL)

        except Exception as e:
            logger.warning(
                "Could not load reranker model '%s': %s. "
                "Re-ranking will be disabled. Set RERANKER_ENABLED=false to silence. "
                "HF_TIMEOUT=%s",
                RERANKER_MODEL,
                e,
                os.getenv("HF_TIMEOUT", "300") if "os" in dir() else "300",
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


def _keyword_relevance(query: str, doc: Document) -> float:
    """Cheap 0..1 fallback when CrossEncoder is off."""
    q_tokens = [t for t in (query or "").replace("\u200c", " ").split() if len(t) > 1]
    if not q_tokens:
        return 0.0
    meta = getattr(doc, "metadata", None) or {}
    blob = " ".join(
        [
            getattr(doc, "page_content", "") or "",
            str(meta.get("law_name") or ""),
            str(meta.get("source") or ""),
            str(meta.get("domain") or ""),
            str(meta.get("subdomain") or ""),
        ]
    )
    hits = sum(1 for t in q_tokens if t in blob)
    # Boost if distinctive multi-char tokens from query appear in law_name
    law = str(meta.get("law_name") or "")
    boost = 0.25 if any(len(t) > 2 and t in law for t in q_tokens) else 0.0
    return min(1.0, hits / max(1, len(q_tokens)) + boost)


def score_documents(
    query: str,
    documents: List[Document],
) -> List[Tuple[Document, float]]:
    """Return (doc, score∈[0,1]) pairs sorted descending by relevance."""
    if not documents:
        return []

    model = get_reranker_model()
    if not model:
        scored = [(d, _keyword_relevance(query, d)) for d in documents]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    try:
        pairs = [[query, doc.page_content] for doc in documents]
        raw_scores = model.predict(pairs)
        scored_docs = [
            (doc, _sigmoid(float(s))) for doc, s in zip(documents, raw_scores)
        ]
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        return scored_docs
    except Exception as e:
        logger.warning("Error during re-ranking: %s. Using keyword scores.", e)
        scored = [(d, _keyword_relevance(query, d)) for d in documents]
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
