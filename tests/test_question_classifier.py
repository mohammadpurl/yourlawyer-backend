"""Tests for question classifier."""

import pytest
from app.services.question_classifier import (
    classify_question,
    get_domain_label,
    LegalDomain,
)


def test_classify_criminal():
    """Test criminal domain classification."""
    question = "مجازات قتل چیست؟"
    domain, confidence = classify_question(question)
    assert domain == LegalDomain.CRIMINAL
    assert confidence > 0


def test_classify_civil():
    """Test civil domain classification."""
    question = "قرارداد خرید و فروش ملک چگونه است؟"
    domain, confidence = classify_question(question)
    assert domain == LegalDomain.CIVIL
    assert confidence > 0


def test_classify_family():
    """Test family domain classification."""
    question = "نفقه چگونه محاسبه می‌شود؟"
    domain, confidence = classify_question(question)
    assert domain == LegalDomain.FAMILY
    assert confidence > 0


def test_classify_commercial():
    """Test commercial domain classification."""
    question = "قوانین مربوط به چک چیست؟"
    domain, confidence = classify_question(question)
    assert domain == LegalDomain.COMMERCIAL
    assert confidence > 0


def test_classify_unknown():
    """Test unknown domain classification."""
    question = "سلام چطوری؟"
    domain, confidence = classify_question(question)
    assert domain == LegalDomain.UNKNOWN
    assert confidence == 0.0


def test_get_domain_label():
    """Test domain label retrieval."""
    assert get_domain_label(LegalDomain.CRIMINAL) == "کیفری"
    assert get_domain_label(LegalDomain.CIVIL) == "مدنی"
    assert get_domain_label(LegalDomain.FAMILY) == "خانواده"
    assert get_domain_label(LegalDomain.COMMERCIAL) == "تجاری"
    assert get_domain_label(LegalDomain.UNKNOWN) == "عمومی"



