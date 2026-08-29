"""Enhanced retrieval with taxonomy domain filtering."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.services.question_classifier import LegalDomain, taxonomy_to_legacy
from app.services.vectorstore import get_vectorstore, prefix_query
from app.services.text_normalize import normalize_persian_text
from app.services.bm25_index import bm25_search
from app.core.config import (
    CHROMA_COLLECTION,
    ENABLE_DOMAIN_FILTERED_RETRIEVAL,
    ENABLE_SUBDOMAIN_FILTERED_RETRIEVAL,
    ENABLE_HYBRID_RETRIEVAL,
    HYBRID_BM25_K,
)

logger = logging.getLogger(__name__)


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
        # Prefix at the edge of embedding search only (not for classify/logs).
        query_text = prefix_query(normalize_persian_text(query))
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

        if ENABLE_HYBRID_RETRIEVAL:
            docs = self._merge_with_bm25(query, docs)

        return docs

    @staticmethod
    def _merge_with_bm25(raw_query: str, dense_docs: List[Document]) -> List[Document]:
        """Union dense hits with BM25 keyword hits, deduped by content_hash.

        Dense-only search can miss exact-term legal queries entirely (see
        module docstring in bm25_index.py). BM25 candidates are appended
        after dense ones so downstream reranking (which re-scores the whole
        set against the query) decides final ordering, not insertion order.
        """
        try:
            kw_docs = bm25_search(raw_query, k=HYBRID_BM25_K)
        except Exception as e:
            logger.warning("BM25 hybrid search failed, dense-only fallback: %s", e)
            return dense_docs

        if not kw_docs:
            return dense_docs

        def _key(d: Document) -> str:
            h = (d.metadata or {}).get("content_hash")
            return str(h) if h else d.page_content

        seen = {_key(d) for d in dense_docs}
        merged = list(dense_docs)
        added = 0
        for d in kw_docs:
            k = _key(d)
            if k in seen:
                continue
            seen.add(k)
            merged.append(d)
            added += 1
        if added:
            logger.info(
                "Hybrid retrieval: +%s BM25-only chunks merged (dense=%s, total=%s)",
                added,
                len(dense_docs),
                len(merged),
            )
        return merged

    def _safe_invoke(self, query_text: str, search_kwargs: Dict[str, Any]) -> List[Document]:
        # Defense in depth: ensure E5 query prefix even if caller forgot.
        query_text = prefix_query(normalize_persian_text(query_text))
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
