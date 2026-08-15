"""Law-name → taxonomy domain mapping for Chroma metadata backfill.

Uses Persian taxonomy keys (same as ``LEGAL_TAXONOMY``). When no rule matches,
returns ``unclassified`` (never null, never a guessed wrong domain).

English slug aliases (civil / family / labor / criminal) are also returned for
reporting; Chroma ``domain`` field stores the Persian key or ``unclassified``.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.taxonomy import DOMAIN_SLUGS, UNCLASSIFIED_DOMAIN


def _normalize_fa(text: str) -> str:
    """Normalize Arabic yeh/kaf and diacritics so law titles match reliably."""
    t = (text or "").replace("\u200c", " ")
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    t = re.sub(r"[\u064B-\u065F\u0670]", "", t)  # harakat
    t = re.sub(r"\s+", " ", t).strip()
    return t


# (pattern on normalized text, domain_fa, subdomain_or_None, slug)
# Order matters: first match wins — put specific laws before broad ones.
_LAW_RULES: list[tuple[str, str, str | None, str]] = [
    # labor first-class
    (r"قانون\s*کار", "کار_و_تامین_اجتماعی", "قرارداد_کار", "labor"),
    (r"تامین\s*اجتماعی|بیمه\s*های\s*اجتماعی|بیمه‌های\s*اجتماعی|بیمه\s*اجتماعی", "کار_و_تامین_اجتماعی", "بیمه_تامین_اجتماعی", "labor"),
    (r"حفاظت\s*فنی|ایمنی\s*کار|آیین\s*نامه\s*ایمنی", "کار_و_تامین_اجتماعی", "ایمنی_و_حفاظت_فنی", "labor"),
    (r"حوادث?\s*ناشی\s*از\s*کار", "کار_و_تامین_اجتماعی", "حوادث_ناشی_از_کار", "labor"),
    (r"بیمه\s*مسئولیت\s*کارفرما|کارگران\s*ساختمان", "کار_و_تامین_اجتماعی", "بیمه_مسئولیت_کارفرما", "labor"),
    (r"روابط\s*کار|بیمه\s*بیکاری|قرارداد\s*کار|هی[اأ]ت\s*تخصصی\s*کار", "کار_و_تامین_اجتماعی", None, "labor"),
    (r"کارگران", "کار_و_تامین_اجتماعی", None, "labor"),
    # family
    (r"حمایت\s*از\s*خانواده", "خانواده", None, "family"),
    (r"ازدواج|طلاق|مهریه|نفقه|حضانت|نکاح|فرزندخواندگی", "خانواده", None, "family"),
    # criminal
    (r"مجازات\s*اسلامی", "کیفری", None, "criminal"),
    (r"آیین\s*دادرسی\s*کیفری", "کیفری", "آیین_دادرسی_کیفری", "criminal"),
    (r"تعزیرات|حدود|قصاص|استرداد\s*مجرم|قانون\s*جرائم?\s*رایانه", "کیفری", None, "criminal"),
    (r"کیفری", "کیفری", None, "criminal"),
    # commercial
    (r"صدور\s*چک|قانون\s*چک", "تجاری_و_اسناد_تجاری", "چک", "commercial"),
    (r"قانون\s*تجارت|ورشکستگی|سفته|برات|شرکت\s*سهامی", "تجاری_و_اسناد_تجاری", None, "commercial"),
    # admin
    (r"دیوان\s*عدالت|استخدام\s*کشوری|خدمات\s*کشوری|هی[اأ]ت\s*دولت", "اداری", None, "admin"),
    # civil (tight patterns — avoid false positives on random titles)
    (r"قانون\s*مدنی", "مدنی", None, "civil"),
    (r"مسئولیت\s*مدنی|ضمان\s*قهری", "مدنی", "مسئولیت_مدنی", "civil"),
    (r"ثبت\s*اسناد", "مدنی", "ثبت_اسناد_و_املاک", "civil"),
    (r"روابط\s*موجر\s*و\s*مستاجر|روابط\s*موجر\s*و\s*مستأجر|قانون\s*اجاره", "مدنی", "قراردادها_و_تعهدات", "civil"),
    (r"امور\s*حسبی|وصیت\s*نامه", "مدنی", "ارث_و_وصیت", "civil"),
    (r"آیین\s*دادرسی\s*مدنی|دادرسی\s*مدنی", "مدنی", None, "civil"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), d, s, slug) for p, d, s, slug in _LAW_RULES]

# High-precision phrases that may appear in chunk body when law_name is vague
_BODY_RULES: list[tuple[str, str, str | None, str]] = [
    (r"قانون\s*مدنی", "مدنی", None, "civil"),
    (r"ضمان\s*قهری", "مدنی", "مسئولیت_مدنی", "civil"),
    (r"قانون\s*کار", "کار_و_تامین_اجتماعی", "قرارداد_کار", "labor"),
    (r"تامین\s*اجتماعی", "کار_و_تامین_اجتماعی", "بیمه_تامین_اجتماعی", "labor"),
    (r"مجازات\s*اسلامی", "کیفری", None, "criminal"),
    (r"آیین\s*دادرسی\s*کیفری", "کیفری", "آیین_دادرسی_کیفری", "criminal"),
    (r"دیوان\s*عدالت", "اداری", None, "admin"),
]
_BODY_COMPILED = [
    (re.compile(p, re.IGNORECASE), d, s, slug) for p, d, s, slug in _BODY_RULES
]


def map_law_to_domain(
    law_name: str | None = None,
    source: str | None = None,
    text_preview: str | None = None,
) -> dict[str, Any]:
    """
    Return ``{domain, subdomain, domain_slug, method}``.

    ``domain`` is a Persian taxonomy key or ``unclassified``.
    Prefer ``law_name`` / ``source`` over body text to avoid false positives.
    """
    title = _normalize_fa(" ".join(x for x in [(law_name or ""), (source or "")] if x))
    body = _normalize_fa((text_preview or "")[:400])

    if not title and not body:
        return {
            "domain": UNCLASSIFIED_DOMAIN,
            "subdomain": None,
            "domain_slug": "unclassified",
            "method": "empty",
        }

    for cre, domain, subdomain, slug in _COMPILED:
        if title and cre.search(title):
            return {
                "domain": domain,
                "subdomain": subdomain,
                "domain_slug": slug,
                "method": "law_name_map",
            }

    for cre, domain, subdomain, slug in _BODY_COMPILED:
        if body and cre.search(body):
            return {
                "domain": domain,
                "subdomain": subdomain,
                "domain_slug": slug,
                "method": "body_precision_map",
            }

    return {
        "domain": UNCLASSIFIED_DOMAIN,
        "subdomain": None,
        "domain_slug": "unclassified",
        "method": "unclassified",
    }


def slug_for_domain(domain: str | None) -> str:
    if not domain or domain in (UNCLASSIFIED_DOMAIN, "نامشخص"):
        return "unclassified"
    for slug, fa in DOMAIN_SLUGS.items():
        if fa == domain:
            return slug
    return "unclassified"
