"""Tests for RAG service."""

from app.services.rag import (
    build_rag_chain,
    _citation_label,
    _extract_citations,
    PERSIAN_LEGAL_SYSTEM_PROMPT,
)
from langchain_core.documents import Document


def test_citation_label_prefers_article_over_filename():
    label = _citation_label(
        {
            "source": "4693937366938194803_قانون مدنی.docx",
            "law_name": "قانون مدنی",
            "unit_kind": "ماده",
            "article_number": "114",
        }
    )
    assert label == "ماده 114 قانون مدنی"


def test_citation_label_falls_back_to_law_name():
    label = _citation_label(
        {
            "source": "123_قانون مجازات اسلامی.pdf",
            "law_name": "قانون مجازات اسلامی",
        }
    )
    assert label == "قانون مجازات اسلامی"


def test_citation_label_strips_id_prefix_from_filename():
    label = _citation_label({"source": "999_آیین‌نامه اجرایی.pdf"})
    assert "آیین‌نامه اجرایی" in label
    assert "999" not in label


def test_extract_citations():
    """Test citation extraction uses legal labels, not raw filenames."""
    docs = [
        Document(
            page_content="test",
            metadata={
                "source": "file1.pdf",
                "law_name": "قانون مدنی",
                "unit_kind": "ماده",
                "article_number": "10",
            },
        ),
        Document(
            page_content="test",
            metadata={
                "source": "file2.pdf",
                "law_name": "قانون مدنی",
                "unit_kind": "ماده",
                "article_number": "114",
            },
        ),
        Document(
            page_content="test",
            metadata={
                "source": "file1.pdf",
                "law_name": "قانون مدنی",
                "unit_kind": "ماده",
                "article_number": "10",
            },
        ),
    ]

    sources = _extract_citations("answer", docs)
    assert sources == ["ماده 10 قانون مدنی", "ماده 114 قانون مدنی"]


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
