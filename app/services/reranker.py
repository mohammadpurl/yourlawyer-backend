"""Re-ranking service for improving RAG retrieval accuracy."""

from typing import List, Optional
from langchain_core.documents import Document
import logging
from app.core.config import RERANKER_ENABLED, RERANKER_MODEL

logger = logging.getLogger(__name__)

_reranker_model = None
_reranker_loading_attempted = False


def get_reranker_model():
    """Get or load reranker model."""
    global _reranker_model, _reranker_loading_attempted

    # Check if reranking is disabled via configuration
    if not RERANKER_ENABLED:
        return None

    if _reranker_model is None and not _reranker_loading_attempted:
        _reranker_loading_attempted = True
        try:
            import os
            from sentence_transformers import CrossEncoder

            # تنظیم timeout برای Hugging Face
            hf_timeout = int(os.getenv("HF_TIMEOUT", "300"))
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(hf_timeout))

            logger.info(
                f"Loading reranker model: {RERANKER_MODEL} (timeout: {hf_timeout}s)"
            )
            _reranker_model = CrossEncoder(RERANKER_MODEL)
            logger.info(f"Reranker model '{RERANKER_MODEL}' loaded successfully")

        except Exception as e:
            logger.warning(
                f"Could not load reranker model '{RERANKER_MODEL}': {e}. "
                "Re-ranking will be disabled. To disable reranking entirely, set RERANKER_ENABLED=false in environment variables. "
                f"If timeout issues persist, try increasing HF_TIMEOUT (current: {os.getenv('HF_TIMEOUT', '300')}s)"
            )
            return None

    return _reranker_model


def rerank_documents(
    query: str,
    documents: List[Document],
    top_k: Optional[int] = None,
) -> List[Document]:
    """
    Re-rank documents based on relevance to query.

    Args:
        query: Search query
        documents: List of documents to re-rank
        top_k: Number of top documents to return (None = return all)

    Returns:
        Re-ranked list of documents
    """
    if not documents:
        return documents

    model = get_reranker_model()
    if not model:
        # If reranker not available, return original order
        return documents[:top_k] if top_k else documents

    try:
        # Prepare pairs for scoring
        pairs = [[query, doc.page_content] for doc in documents]

        # Get scores
        scores = model.predict(pairs)

        # Sort by score (descending)
        scored_docs = list(zip(documents, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # Return top_k documents
        reranked = [doc for doc, score in scored_docs]
        if top_k:
            reranked = reranked[:top_k]

        logger.info(
            f"Re-ranked {len(documents)} documents, returning top {len(reranked)}"
        )
        return reranked

    except Exception as e:
        logger.warning(f"Error during re-ranking: {e}. Returning original order.")
        return documents[:top_k] if top_k else documents
