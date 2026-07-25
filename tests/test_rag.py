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
    """Test that prompt contains grounding constraints."""
    assert "منابع" in PERSIAN_LEGAL_SYSTEM_PROMPT or "بازیابی" in PERSIAN_LEGAL_SYSTEM_PROMPT
    assert "دانش عمومی" in PERSIAN_LEGAL_SYSTEM_PROMPT or "حافظه" in PERSIAN_LEGAL_SYSTEM_PROMPT
    assert "اطلاعات کافی در منابع موجود" in PERSIAN_LEGAL_SYSTEM_PROMPT


def test_build_rag_chain(monkeypatch):
    """Test RAG chain building without loading embedding models."""
    from langchain_core.documents import Document as LCDocument

    class _FakeVS:
        def as_retriever(self, search_kwargs=None):
            class _R:
                def invoke(self, q):
                    return [LCDocument(page_content="test", metadata={"source": "a.pdf"})]

            return _R()

    monkeypatch.setattr("app.services.rag.get_vectorstore", lambda: _FakeVS())
    monkeypatch.setattr("app.services.rag.OPENAI_API_KEY", None)
    monkeypatch.setattr("app.services.rag.OLLAMA_MODEL", None)

    chain = build_rag_chain(k=3, use_enhanced_retrieval=False, use_reranking=False)
    assert callable(chain)
    assert hasattr(chain, "__call__")



