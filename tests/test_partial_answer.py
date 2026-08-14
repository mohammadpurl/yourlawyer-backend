"""Tests for partial-answer guard and workplace query expansion helpers."""

from app.services.rag import (
    _is_full_refuse_answer,
    _needs_workplace_expansion,
    _dedupe_docs,
    RAG_NO_CONTEXT_MESSAGE,
)
from langchain_core.documents import Document


def test_full_refuse_detection():
    assert _is_full_refuse_answer(RAG_NO_CONTEXT_MESSAGE)
    assert _is_full_refuse_answer(
        RAG_NO_CONTEXT_MESSAGE + " برای بررسی قانون کار لازم است."
    )
    assert not _is_full_refuse_answer(
        "آنچه از منابع برمی‌آید: ماده ۱ بیمه کارگران ساختمانی..."
    )


def test_workplace_expansion_trigger():
    q = (
        "کارگر ساختمانی از ساختمان سقوط کرده و کارفرما وسایل ایمنی "
        "فراهم نکرده مالک ساختمان مقصر است"
    )
    assert _needs_workplace_expansion(q)
    assert not _needs_workplace_expansion("مهریه زن بعد از طلاق چقدر است")


def test_dedupe_docs_by_content_hash():
    a = Document(page_content="x", metadata={"content_hash": "h1"})
    b = Document(page_content="y", metadata={"content_hash": "h1"})
    c = Document(page_content="z", metadata={"content_hash": "h2"})
    out = _dedupe_docs([a, b, c])
    assert len(out) == 2
