"""Tests for RAG service."""

import pytest
from app.services.rag import build_rag_chain, _extract_citations, PERSIAN_LEGAL_SYSTEM_PROMPT
from langchain_core.documents import Document


def test_extract_citations():
    """Test citation extraction."""
    docs = [
        Document(page_content="test", metadata={"source": "file1.pdf"}),
        Document(page_content="test", metadata={"source": "file2.pdf"}),
        Document(page_content="test", metadata={"source": "file1.pdf"}),  # Duplicate
    ]
    
    sources = _extract_citations("answer", docs)
    assert len(sources) == 2
    assert "file1.pdf" in sources
    assert "file2.pdf" in sources


def test_prompt_content():
    """Test that prompt contains required elements."""
    assert "دستیار حقوقی" in PERSIAN_LEGAL_SYSTEM_PROMPT
    assert "مواد قانونی" in PERSIAN_LEGAL_SYSTEM_PROMPT
    assert "منبع" in PERSIAN_LEGAL_SYSTEM_PROMPT


def test_build_rag_chain():
    """Test RAG chain building."""
    # Test without LLM (fallback mode)
    chain = build_rag_chain(k=3, use_enhanced_retrieval=False, use_reranking=False)
    assert callable(chain)
    
    # Test that it returns a function
    assert hasattr(chain, "__call__")



