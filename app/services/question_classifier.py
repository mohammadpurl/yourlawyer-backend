"""Thin compatibility layer over ``app.services.taxonomy``.

Do not add a second keyword taxonomy here — LEGAL_TAXONOMY is the only source
of truth. This module only maps taxonomy domains to the legacy LegalDomain
enum used by older response fields / tests.
"""

from __future__ import annotations

from enum import Enum

from app.services.taxonomy import classify_confident, classify_query


class LegalDomain(str, Enum):
    """Legacy flat domains (mapped from hierarchical taxonomy)."""

    CRIMINAL = "criminal"
    CIVIL = "civil"
    FAMILY = "family"
    COMMERCIAL = "commercial"
    UNKNOWN = "unknown"


# Persian taxonomy domain → legacy enum
_TAXONOMY_TO_LEGACY: dict[str, LegalDomain] = {
    "کیفری": LegalDomain.CRIMINAL,
    "مدنی": LegalDomain.CIVIL,
    "خانواده": LegalDomain.FAMILY,
    "تجاری_و_اسناد_تجاری": LegalDomain.COMMERCIAL,
    "اداری": LegalDomain.CIVIL,
    "کار_و_تامین_اجتماعی": LegalDomain.CIVIL,
}

_LEGACY_LABELS: dict[LegalDomain, str] = {
    LegalDomain.CRIMINAL: "کیفری",
    LegalDomain.CIVIL: "مدنی",
    LegalDomain.FAMILY: "خانواده",
    LegalDomain.COMMERCIAL: "تجاری",
    LegalDomain.UNKNOWN: "عمومی",
}


def taxonomy_to_legacy(domain: str | None) -> LegalDomain:
    if not domain:
        return LegalDomain.UNKNOWN
    return _TAXONOMY_TO_LEGACY.get(domain, LegalDomain.UNKNOWN)


def classify_question(question: str) -> tuple[LegalDomain, float]:
    """Classify via taxonomy; return legacy (LegalDomain, confidence)."""
    result = classify_query(question)
    domain = taxonomy_to_legacy(result.get("domain"))
    confidence = float(result.get("confidence") or 0.0)
    if domain == LegalDomain.UNKNOWN:
        confidence = 0.0
    return domain, confidence


def get_domain_label(domain: LegalDomain | str | None) -> str:
    """Persian label for API responses."""
    if domain is None:
        return "عمومی"
    if isinstance(domain, str):
        # Already a taxonomy Persian key, or legacy value
        if domain in _TAXONOMY_TO_LEGACY:
            return domain
        try:
            domain = LegalDomain(domain)
        except ValueError:
            return domain or "عمومی"
    return _LEGACY_LABELS.get(domain, "عمومی")


__all__ = [
    "LegalDomain",
    "classify_question",
    "classify_query",
    "classify_confident",
    "get_domain_label",
    "taxonomy_to_legacy",
]
