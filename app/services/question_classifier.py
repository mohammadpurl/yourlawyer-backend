"""Legal question type classifier for Persian legal queries."""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

# Legal domain categories
LEGAL_DOMAINS = {
    "criminal": {
        "keywords": [
            "جرم",
            "مجازات",
            "زندان",
            "حبس",
            "جزا",
            "کیفر",
            "دعوای کیفری",
            "دادگاه کیفری",
            "دادستان",
            "شکایت کیفری",
            "قتل",
            "سرقت",
            "کلاهبرداری",
            "خیانت",
            "توهین",
            "ضرب و جرح",
        ],
        "label": "کیفری",
    },
    "civil": {
        "keywords": [
            "حقوق مدنی",
            "عقد",
            "قرارداد",
            "خرید و فروش",
            "اجاره",
            "ملک",
            "ارث",
            "وصیت",
            "ضمان",
            "کفالت",
            "رهن",
            "عقد نکاح",
            "طلاق",
            "نفقه",
            "مهریه",
        ],
        "label": "مدنی",
    },
    "family": {
        "keywords": [
            "خانواده",
            "ازدواج",
            "طلاق",
            "نفقه",
            "مهریه",
            "حضانت",
            "ولایت",
            "نسب",
            "عقد نکاح",
            "صیغه",
            "عده",
            "نشوز",
            "شیربها",
        ],
        "label": "خانواده",
    },
    "commercial": {
        "keywords": [
            "تجاری",
            "شرکت",
            "سهامی",
            "با مسئولیت محدود",
            "سفته",
            "برات",
            "چک",
            "اسناد تجاری",
            "ورشکستگی",
            "تجارت",
            "بازرگانی",
            "قرارداد تجاری",
        ],
        "label": "تجاری",
    },
}


class LegalDomain(str, Enum):
    """Legal domain categories."""

    CRIMINAL = "criminal"
    CIVIL = "civil"
    FAMILY = "family"
    COMMERCIAL = "commercial"
    UNKNOWN = "unknown"


def classify_question(question: str) -> tuple[LegalDomain, float]:
    """Classify a Persian legal question into a legal domain.

    Returns:
        Tuple of (domain, confidence_score)
    """
    question_lower = question.lower()
    scores: dict[LegalDomain, float] = {}

    for domain_key, domain_info in LEGAL_DOMAINS.items():
        domain = LegalDomain(domain_key)
        score = 0.0
        keywords = domain_info["keywords"]

        for keyword in keywords:
            if keyword in question_lower:
                score += 1.0

        if score > 0:
            scores[domain] = score / len(keywords)

    if not scores:
        return LegalDomain.UNKNOWN, 0.0

    best_domain = max(scores.items(), key=lambda x: x[1])
    return best_domain[0], best_domain[1]


def get_domain_label(domain: LegalDomain) -> str:
    """Get Persian label for a legal domain."""
    if domain == LegalDomain.UNKNOWN:
        return "عمومی"
    return LEGAL_DOMAINS[domain.value]["label"]
