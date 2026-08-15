"""Enhanced retrieval with taxonomy domain filtering."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.services.question_classifier import LegalDomain, taxonomy_to_legacy
from app.services.vectorstore import get_vectorstore
from app.core.config import (
    CHROMA_COLLECTION,
    ENABLE_DOMAIN_FILTERED_RETRIEVAL,
    ENABLE_SUBDOMAIN_FILTERED_RETRIEVAL,
)

logger = logging.getLogger(__name__)

_QUERY_PREFIX = "query: "


def _as_e5_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q
    if q.startswith(_QUERY_PREFIX):
        return q
    return f"{_QUERY_PREFIX}{q}"


class EnhancedRetriever:
    """Retriever with hierarchical taxonomy metadata filters."""

    def __init__(
        self,
        collection_name: str | None = None,
        enable_domain_filter: bool = False,
        domain_filter_min_confidence: float = 0.35,
    ):
        self.vectorstore = get_vectorstore(collection_name or CHROMA_COLLECTION)
        # Kept for API compat; filtering is controlled by ENABLE_DOMAIN_FILTERED_RETRIEVAL
        self.enable_domain_filter = enable_domain_filter
        self.domain_filter_min_confidence = domain_filter_min_confidence

    def retrieve(
        self,
        query: str,
        k: int = 5,
        domain: Optional[LegalDomain] = None,
        document_type: Optional[str] = None,
        taxonomy_domain: Optional[str] = None,
        taxonomy_subdomain: Optional[str] = None,
    ) -> List[Document]:
        """Retrieve with optional taxonomy domain/subdomain filter + fallbacks."""
        query_text = _as_e5_query(query)
        search_kwargs: Dict[str, Any] = {"k": k}

        if (
            ENABLE_DOMAIN_FILTERED_RETRIEVAL
            and taxonomy_domain
            and taxonomy_domain not in ("نامشخص", "unclassified", None, "")
        ):
            if (
                ENABLE_SUBDOMAIN_FILTERED_RETRIEVAL
                and taxonomy_subdomain
            ):
                search_kwargs["filter"] = {
                    "$and": [
                        {"domain": taxonomy_domain},
                        {"subdomain": taxonomy_subdomain},
                    ]
                }
            else:
                # Domain-only: safer after law-name backfill (many chunks lack subdomain)
                search_kwargs["filter"] = {"domain": taxonomy_domain}
        elif document_type:
            search_kwargs["filter"] = {"document_type": document_type}

        docs = self._safe_invoke(query_text, search_kwargs)

        if (
            (not docs or len(docs) < max(1, k // 2))
            and taxonomy_domain
            and taxonomy_subdomain
            and ENABLE_DOMAIN_FILTERED_RETRIEVAL
        ):
            logger.info(
                "Subdomain filter weak (got %s); falling back to domain=%s",
                len(docs) if docs else 0,
                taxonomy_domain,
            )
            docs = self._safe_invoke(
                query_text, {"k": k, "filter": {"domain": taxonomy_domain}}
            )

        if not docs and search_kwargs.get("filter"):
            logger.info(
                "Domain/type filter returned 0 docs (filter=%s); unfiltered fallback",
                search_kwargs.get("filter"),
            )
            docs = self._safe_invoke(query_text, {"k": k})

        return docs

    def _safe_invoke(self, query_text: str, search_kwargs: Dict[str, Any]) -> List[Document]:
        try:
            retriever = self.vectorstore.as_retriever(search_kwargs=search_kwargs)
            return list(retriever.invoke(query_text) or [])
        except Exception as e:
            logger.warning(
                "Chroma retriever.invoke failed (filter=%s): %s",
                search_kwargs.get("filter"),
                e,
            )
            try:
                k = int(search_kwargs.get("k") or 5)
                filt = search_kwargs.get("filter")
                if filt:
                    return list(
                        self.vectorstore.similarity_search(query_text, k=k, filter=filt)
                        or []
                    )
                return list(self.vectorstore.similarity_search(query_text, k=k) or [])
            except Exception as e2:
                logger.warning("Chroma similarity_search also failed: %s", e2)
                return []

    def retrieve_with_classification(
        self, question: str, k: int = 5
    ) -> tuple[List[Document], LegalDomain, float]:
        """Classify once via taxonomy, then retrieve."""
        from app.services.taxonomy import classify_confident

        tax = classify_confident(question)
        tax_domain = tax.get("domain") if tax.get("confident") else None
        tax_sub = tax.get("subdomain") if tax.get("confident") else None
        domain = taxonomy_to_legacy(tax.get("domain"))
        confidence = float(tax.get("confidence") or 0.0)
        if domain == LegalDomain.UNKNOWN:
            confidence = 0.0

        docs = self.retrieve(
            question,
            k=k,
            taxonomy_domain=tax_domain,
            taxonomy_subdomain=tax_sub,
        )
        return docs, domain, confidence
