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
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ؤ", "و")
    t = re.sub(r"[\u064B-\u065F\u0670]", "", t)  # harakat
    t = re.sub(r"\s+", " ", t).strip()
    return t


# (pattern on normalized text, domain_fa, subdomain_or_None, slug)
# Order matters: first match wins — put specific laws before broad ones.
_LAW_RULES: list[tuple[str, str, str | None, str]] = [
    # labor first-class
    (r"قانون\s*کار", "کار_و_تامین_اجتماعی", "قرارداد_کار", "labor"),
    (r"تامین\s*اجتماعی|بیمه\s*های\s*اجتماعی|بیمه‌های\s*اجتماعی|بیمه\s*اجتماعی", "کار_و_تامین_اجتماعی", "بیمه_تامین_اجتماعی", "labor"),
    (r"حفاظت\s*فنی|ایمنی\s*کار|آیین\s*نامه\s*ایمنی|ایمنی\s*در\s|سخت\s*و\s*زیان|تونل\s*سازی", "کار_و_تامین_اجتماعی", "ایمنی_و_حفاظت_فنی", "labor"),
    (r"حوادث?\s*ناشی\s*از\s*کار", "کار_و_تامین_اجتماعی", "حوادث_ناشی_از_کار", "labor"),
    (r"بیمه\s*مسئولیت\s*کارفرما|کارگران\s*ساختمان", "کار_و_تامین_اجتماعی", "بیمه_مسئولیت_کارفرما", "labor"),
    (r"روابط\s*کار|بیمه\s*بیکاری|قرارداد\s*کار|هی[اأ]ت\s*تخصصی\s*کار|سازمان\s*تامین", "کار_و_تامین_اجتماعی", None, "labor"),
    (r"کارگران|کارفرما", "کار_و_تامین_اجتماعی", None, "labor"),
    # family
    (r"حمایت\s*از\s*خانواده|حمایت\s*خانواده", "خانواده", None, "family"),
    (r"ازدواج|طلاق|مهریه|نفقه|حضانت|نکاح|فرزندخواندگی|عده\s|تمکین", "خانواده", None, "family"),
    # criminal (expand coverage for unclassified backfill)
    (r"مجازات\s*اسلامی", "کیفری", None, "criminal"),
    (r"آیین\s*دادرسی\s*کیفری|دادرسی\s*کیفری|امور\s*کیفری", "کیفری", "آیین_دادرسی_کیفری", "criminal"),
    (r"اجرای\s*احکام\s*کیفری|نحوه\s*اجرای\s*محکومیت", "کیفری", None, "criminal"),
    (r"تعزیرات|حدود|قصاص|استرداد\s*مجرم|قانون\s*جرائم?\s*رایانه", "کیفری", None, "criminal"),
    (r"مواد\s*مخدر|قاچاق\s*سلاح|پول\s*شویی|پولشویی|ارتشا|اختلاس|کلاهبرداری", "کیفری", None, "criminal"),
    (r"سرقت|قتل\s|دیه\s|دیات|محاربه|افساد\s*فی\s*الارض", "کیفری", None, "criminal"),
    (r"کیفری|جزای\s*نقدی\s*تعزیری|جرائم?\s*نیروهای\s*مسلح|کیفر\s*ارتش|دادرسی\s*و\s*کیفر", "کیفری", None, "criminal"),
    # commercial
    (r"صدور\s*چک|قانون\s*چک|برگشت\s*چک", "تجاری_و_اسناد_تجاری", "چک", "commercial"),
    (r"قانون\s*تجارت|ورشکستگی|سفته|برات|شرکت\s*سهامی|مسئولیت\s*محدود", "تجاری_و_اسناد_تجاری", None, "commercial"),
    # admin (constitution, elections, treaties, budget — common unclassified titles)
    (r"دیوان\s*عدالت|استخدام\s*کشوری|خدمات\s*کشوری|هی[اأ]ت\s*دولت|مناقصات", "اداری", None, "admin"),
    (r"قانون\s*اساسی|شورای\s*اسلامی|انتخابات|مجلس\s*شورا|شهردار", "اداری", None, "admin"),
    (r"بودجه|برنامه\s*پنج|عمرانی|توسعه\s*جمهوری|گمرک", "اداری", None, "admin"),
    (r"موافقتنامه|کنوانسیون|کنفرانس|الحاق\s*دولت|معاهده|قطعنامه", "اداری", None, "admin"),
    (r"سند\s*تحول|قوه\s*قضائیه|تحول\s*قضائی", "اداری", None, "admin"),
    # civil (tight patterns — avoid false positives on random titles)
    (r"قانون\s*مدنی", "مدنی", None, "civil"),
    (r"مسئولیت\s*مدنی|ضمان\s*قهری", "مدنی", "مسئولیت_مدنی", "civil"),
    (r"ثبت\s*اسناد|املاک", "مدنی", "ثبت_اسناد_و_املاک", "civil"),
    (r"روابط\s*موجر\s*و\s*مستاجر|روابط\s*موجر\s*و\s*مستأجر|قانون\s*اجاره", "مدنی", "قراردادها_و_تعهدات", "civil"),
    (r"امور\s*حسبی|وصیت|ارث\s", "مدنی", "ارث_و_وصیت", "civil"),
    (r"آیین\s*دادرسی\s*مدنی|دادرسی\s*مدنی|امور\s*مدنی|اجرای\s*احکام\s*مدنی", "مدنی", None, "civil"),
    (r"بیع|اجاره\s*مکان|عقود\s*معین", "مدنی", "قراردادها_و_تعهدات", "civil"),
    # tax / environment often unclassified — map narrowly by title
    (r"مالیات\s*های\s*مستقیم|مالیاتهای\s*مستقیم|قانون\s*مالیات", "اداری", None, "admin"),
    (r"محیط\s*زیست|آلودگی\s*هوا|پسماند", "اداری", None, "admin"),
    (r"تعرفه\s*دستمزد\s*کارشناسان", "مدنی", None, "civil"),
    (r"دیوان\s*عالی\s*کشور|وحدت\s*رویه", "کیفری", None, "criminal"),
    (r"خدمت\s*وظیفه|نظام\s*وظیفه", "اداری", None, "admin"),
    (r"اراضی\s*زراعی|کاربری\s*اراضی|باغها", "مدنی", "ثبت_اسناد_و_املاک", "civil"),
    (r"اساسنامه|تصویب\s*نامه|بخشنامه|آیین\s*نامه\s*اجرایی|تصمیم\s*قانونی", "اداری", None, "admin"),
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
    (r"قانون\s*صدور\s*چک", "تجاری_و_اسناد_تجاری", "چک", "commercial"),
    (r"دیوان\s*عدالت", "اداری", None, "admin"),
    (r"حمایت\s*خانواده", "خانواده", None, "family"),
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
