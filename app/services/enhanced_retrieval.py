"""Enhanced retrieval with domain filtering and metadata support."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.services.question_classifier import (
    LegalDomain,
    classify_question,
    get_domain_label,
)
from app.services.vectorstore import get_vectorstore


class EnhancedRetriever:
    """Retriever with domain filtering and metadata support."""

    def __init__(
        self,
        collection_name: str = "legal-texts",
        enable_domain_filter: bool = True,
    ):
        self.vectorstore = get_vectorstore(collection_name)
        self.enable_domain_filter = enable_domain_filter

    def retrieve(
        self,
        query: str,
        k: int = 5,
        domain: Optional[LegalDomain] = None,
        document_type: Optional[str] = None,
    ) -> List[Document]:
        """Retrieve documents with optional filtering.

        Args:
            query: Search query
            k: Number of documents to retrieve
            domain: Optional legal domain filter
            document_type: Optional document type filter (law/regulation/ruling)

        Returns:
            List of retrieved documents
        """
        # Build filter if needed (Chroma uses 'where' for metadata filtering)
        search_kwargs: Dict[str, Any] = {"k": k}

        if self.enable_domain_filter and domain and domain != LegalDomain.UNKNOWN:
            where_clause: Dict[str, Any] = {"legal_domain": domain.value}

            if document_type:
                where_clause["document_type"] = document_type

            search_kwargs["filter"] = where_clause
        elif document_type:
            search_kwargs["filter"] = {"document_type": document_type}

        # Retrieve with filter
        retriever = self.vectorstore.as_retriever(search_kwargs=search_kwargs)

        docs = retriever.invoke(query)
        return docs

    def retrieve_with_classification(
        self, question: str, k: int = 5
    ) -> tuple[List[Document], LegalDomain, float]:
        """Retrieve documents after classifying the question.

        Returns:
            Tuple of (documents, detected_domain, confidence)
        """
        domain, confidence = classify_question(question)
        docs = self.retrieve(question, k=k, domain=domain)
        return docs, domain, confidence
