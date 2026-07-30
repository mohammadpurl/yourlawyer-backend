"""Enhanced retrieval with domain filtering and metadata support."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.services.question_classifier import (
    LegalDomain,
    classify_question,
)
from app.services.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# E5 embedding models expect this prefix on queries.
_QUERY_PREFIX = "query: "


def _as_e5_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q
    if q.startswith(_QUERY_PREFIX):
        return q
    return f"{_QUERY_PREFIX}{q}"


class EnhancedRetriever:
    """Retriever with domain filtering and metadata support."""

    def __init__(
        self,
        collection_name: str = "legal-texts",
        enable_domain_filter: bool = False,
        domain_filter_min_confidence: float = 0.35,
    ):
        self.vectorstore = get_vectorstore(collection_name)
        self.enable_domain_filter = enable_domain_filter
        self.domain_filter_min_confidence = domain_filter_min_confidence

    def retrieve(
        self,
        query: str,
        k: int = 5,
        domain: Optional[LegalDomain] = None,
        document_type: Optional[str] = None,
    ) -> List[Document]:
        """Retrieve documents with optional filtering.

        If a metadata filter returns no hits (common when corpus is tagged
        ``legal_domain=unknown``), falls back to an unfiltered search so RAG
        still has grounded chunks.
        """
        query_text = _as_e5_query(query)
        search_kwargs: Dict[str, Any] = {"k": k}
        where_clause: Dict[str, Any] | None = None

        if self.enable_domain_filter and domain and domain != LegalDomain.UNKNOWN:
            where_clause = {"legal_domain": domain.value}
            if document_type:
                where_clause["document_type"] = document_type
            search_kwargs["filter"] = where_clause
        elif document_type:
            where_clause = {"document_type": document_type}
            search_kwargs["filter"] = where_clause

        docs = self._safe_invoke(query_text, search_kwargs)

        # Corpus is largely tagged legal_domain=unknown — domain filters often
        # return zero chunks. Always fall back so grounding still works.
        if not docs and search_kwargs.get("filter"):
            logger.info(
                "Domain/type filter returned 0 docs (filter=%s); falling back to unfiltered retrieve",
                search_kwargs.get("filter"),
            )
            fallback_kwargs: Dict[str, Any] = {"k": k}
            docs = self._safe_invoke(query_text, fallback_kwargs)

        return docs

    def _safe_invoke(self, query_text: str, search_kwargs: Dict[str, Any]) -> List[Document]:
        try:
            retriever = self.vectorstore.as_retriever(search_kwargs=search_kwargs)
            docs = retriever.invoke(query_text)
            return list(docs or [])
        except Exception as e:
            logger.warning(
                "Chroma retriever.invoke failed (filter=%s): %s — trying similarity_search",
                search_kwargs.get("filter"),
                e,
            )
            try:
                k = int(search_kwargs.get("k") or 5)
                filt = search_kwargs.get("filter")
                if filt:
                    return list(
                        self.vectorstore.similarity_search(
                            query_text, k=k, filter=filt
                        )
                        or []
                    )
                return list(self.vectorstore.similarity_search(query_text, k=k) or [])
            except Exception as e2:
                logger.warning("Chroma similarity_search also failed: %s", e2)
                return []

    def retrieve_with_classification(
        self, question: str, k: int = 5
    ) -> tuple[List[Document], LegalDomain, float]:
        """Retrieve documents after classifying the question.

        Returns:
            Tuple of (documents, detected_domain, confidence)
        """
        domain, confidence = classify_question(question)
        apply_domain = domain
        if confidence < self.domain_filter_min_confidence:
            # Low-confidence labels must not hard-filter the corpus.
            apply_domain = LegalDomain.UNKNOWN
        docs = self.retrieve(question, k=k, domain=apply_domain)
        return docs, domain, confidence
