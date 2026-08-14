"""Tests for hierarchical legal taxonomy + relevance filtering."""

from langchain_core.documents import Document

from app.services.taxonomy import (
    flatten_taxonomy,
    heuristic_tag_text,
    is_valid_domain,
    is_valid_subdomain,
    classify_query,
    normalize_classify_result,
)
from app.services.reranker import filter_by_min_score, _keyword_relevance


def test_flatten_taxonomy_has_check_leaf():
    rows = flatten_taxonomy()
    assert any(r.get("domain") == "تجاری_و_اسناد_تجاری" for r in rows)
    assert any(r.get("subdomain") == "چک" for r in rows)


def test_heuristic_check_not_extradition():
    tag = heuristic_tag_text(
        "قانون صدور چک.docx",
        "قانون صدور چک در مورد برگشت چک و چک بلامحل مقررات وضع کرده است.",
    )
    assert tag["domain"] == "تجاری_و_اسناد_تجاری"
    assert tag["subdomain"] == "چک"


def test_heuristic_extradition_criminal():
    tag = heuristic_tag_text(
        "معاهده استرداد مجرمین.docx",
        "معاهده استرداد مجرمین بین جمهوری اسلامی ایران و ویتنام ماده ۱۲",
    )
    assert tag["domain"] == "کیفری"


def test_normalize_rejects_invalid_domain():
    out = normalize_classify_result(
        {"domain": "foo", "subdomain": "bar", "confidence": 0.9, "method": "t"}
    )
    assert out["domain"] is None
    assert out["confidence"] == 0.0


def test_normalize_keeps_valid():
    out = normalize_classify_result(
        {
            "domain": "تجاری_و_اسناد_تجاری",
            "subdomain": "چک",
            "confidence": 0.88,
            "method": "llm",
        }
    )
    assert is_valid_domain(out["domain"])
    assert is_valid_subdomain(out["domain"], out["subdomain"])
    assert out["confidence"] == 0.88


def test_classify_query_heuristic_check(monkeypatch):
    monkeypatch.setattr("app.services.taxonomy.TAXONOMY_LLM_CLASSIFY", False, raising=False)
    monkeypatch.setenv("TAXONOMY_LLM_CLASSIFY", "false")
    monkeypatch.setattr("app.services.taxonomy._llm_classify", lambda q: None)
    monkeypatch.setattr("app.services.taxonomy._get_cached", lambda q: None)
    monkeypatch.setattr(
        "app.services.taxonomy._set_cached", lambda q, r, ttl=3600: None
    )
    result = classify_query("قانون برگشت چک چیست")
    assert result["domain"] == "تجاری_و_اسناد_تجاری"
    assert result["subdomain"] == "چک"
    assert result["confidence"] > 0.5


def test_heuristic_workplace_accident_labor():
    tag = heuristic_tag_text(
        "آیین نامه حفاظت فنی کارگاه.docx",
        "حادثه ناشی از کار و وسایل ایمنی کارگر ساختمانی و مسئولیت کارفرما",
    )
    assert tag["domain"] == "کار_و_تامین_اجتماعی"
    assert tag["subdomain"] in {
        "حوادث_ناشی_از_کار",
        "ایمنی_و_حفاظت_فنی",
        "بیمه_مسئولیت_کارفرما",
        "قرارداد_کار",
    }


def test_labor_subdomains_registered():
    assert is_valid_subdomain("کار_و_تامین_اجتماعی", "حوادث_ناشی_از_کار")
    assert is_valid_subdomain("کار_و_تامین_اجتماعی", "ایمنی_و_حفاظت_فنی")
    assert is_valid_subdomain("کار_و_تامین_اجتماعی", "بیمه_مسئولیت_کارفرما")


def test_filter_by_min_score_drops_low():
    docs = [
        Document(page_content="a", metadata={}),
        Document(page_content="b", metadata={}),
    ]
    scored = [(docs[0], 0.9), (docs[1], 0.1)]
    kept = filter_by_min_score(scored, min_score=0.5)
    assert kept == [docs[0]]


def test_keyword_relevance_prefers_check_law():
    q = "قانون برگشت چک"
    good = Document(
        page_content="صدور چک و برگشت چک",
        metadata={"law_name": "قانون صدور چک"},
    )
    bad = Document(
        page_content="استرداد مجرمین بین ایران و ویتنام",
        metadata={"law_name": "معاهده استرداد مجرمین"},
    )
    assert _keyword_relevance(q, good) > _keyword_relevance(q, bad)
