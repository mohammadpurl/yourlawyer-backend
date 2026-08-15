"""Tests for reranker hybrid discrimination + law→domain map."""

from langchain_core.documents import Document

from app.services.domain_law_map import map_law_to_domain
from app.services.reranker import _keyword_relevance, score_documents
import app.services.reranker as rr


def test_keyword_prefers_civil_code_for_zamane_qahri():
    q = "ضمان قهری در قانون مدنی چیست"
    rel = Document(
        page_content="ماده ۳۰۷ قانون مدنی امور ذیل موجب ضمان قهری است غصب اتلاف تسبیب",
        metadata={"law_name": "قانون مدنی"},
    )
    irr = Document(
        page_content="مالکان کشتی‌های ایرانی مشمول مقاوله‌نامه کار دریایی",
        metadata={"law_name": "آیین نامه کار دریایی"},
    )
    assert _keyword_relevance(q, rel) > _keyword_relevance(q, irr)


def test_score_documents_hybrid_discriminates(monkeypatch):
    """Even with collapsed CE scores, hybrid must separate relevant/irrelevant."""

    class FakeCE:
        def predict(self, pairs):
            # Saturate like English MiniLM on Persian
            return [9.0 for _ in pairs]

    monkeypatch.setattr(rr, "get_reranker_model", lambda: FakeCE())
    monkeypatch.setattr(rr, "RERANKER_COLLAPSE_SPREAD", 0.05)

    q = "ضمان قهری در قانون مدنی چیست"
    docs = [
        Document(
            page_content="ماده ۳۰۷ قانون مدنی موجب ضمان قهری است",
            metadata={"law_name": "قانون مدنی", "label": "rel"},
        ),
        Document(
            page_content="بازگرداندن دریانوردان طبق قرارداد کار دریایی",
            metadata={"law_name": "آیین نامه کار دریایی", "label": "irr"},
        ),
    ]
    scored = score_documents(q, docs)
    by = {(d.metadata["label"]): s for d, s in scored}
    assert by["rel"] - by["irr"] >= 0.3


def test_map_law_civil():
    m = map_law_to_domain(law_name="قانون مدنی")
    assert m["domain"] == "مدنی"
    assert m["domain_slug"] == "civil"


def test_map_law_labor():
    m = map_law_to_domain(law_name="قانون کار")
    assert m["domain"] == "کار_و_تامین_اجتماعی"
    assert m["domain_slug"] == "labor"


def test_map_law_unclassified():
    m = map_law_to_domain(law_name="سند ناشناس الفبای قمری")
    assert m["domain"] == "unclassified"
