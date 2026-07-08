"""Tests for legal document ingestion helpers."""

from app.services.ingestion import (
    E5_PASSAGE_PREFIX,
    _content_hash,
    _e5_passage_text,
    chunk_text,
    parse_source_metadata,
)


def test_e5_passage_prefix_is_applied_once():
    assert _e5_passage_text("متن قانون") == f"{E5_PASSAGE_PREFIX}متن قانون"
    prefixed = f"{E5_PASSAGE_PREFIX}متن قانون"
    assert _e5_passage_text(prefixed) == prefixed


def test_parse_source_metadata_with_doc_id():
    metadata = parse_source_metadata("4693937366938194803_قانون مجازات اسلامي.docx")
    assert metadata["doc_id"] == "4693937366938194803"
    assert metadata["law_name"] == "قانون مجازات اسلامي"


def test_parse_source_metadata_without_doc_id():
    metadata = parse_source_metadata("قانون کار.docx")
    assert "doc_id" not in metadata
    assert metadata["law_name"] == "قانون کار"


def test_chunk_text_adds_passage_prefix_and_metadata():
    text = "ماده 1\nاین یک متن تستی است.\n\nماده 2\nمتن ماده دوم."
    docs = chunk_text(text, source="1234567890_قانون تست.docx")

    assert docs
    assert all(doc.page_content.startswith(E5_PASSAGE_PREFIX) for doc in docs)
    assert docs[0].metadata["source"] == "1234567890_قانون تست.docx"
    assert docs[0].metadata["doc_id"] == "1234567890"
    assert docs[0].metadata["law_name"] == "قانون تست"
    assert docs[0].metadata["document_type"] == "law"
    assert "content_hash" in docs[0].metadata
    assert docs[0].metadata["unit_kind"] == "ماده"
    assert docs[0].metadata["article_number"] == "1"


def test_content_hash_is_stable():
    assert _content_hash("  متن   تست  ") == _content_hash("متن تست")
