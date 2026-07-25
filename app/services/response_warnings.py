"""User-facing response warning banners (citation grounding, etc.)."""

from __future__ import annotations

_WARNINGS = {
    "citation_unverified": (
        "⚠️ هشدار مهم: برخی استنادهای قانونی این پاسخ در منابع بازیابی‌شده یافت نشد "
        "و ممکن است نادرست باشد. لطفاً قبل از اتکا، متن قانون را بررسی کنید.\n\n"
    ),
    "partial_citation": (
        "⚠️ هشدار: بخشی از استنادهای این پاسخ در منابع بازیابی‌شده تأیید نشد. "
        "با احتیاط استفاده کنید.\n\n"
    ),
    "no_citation": (
        "ℹ️ توجه: این پاسخ استناد صریح به ماده/تبصره ندارد یا استناد قابل‌استخراجی نداشت.\n\n"
    ),
}


def prepend_strong_warning(text: str, *, reason: str) -> str:
    prefix = _WARNINGS.get(reason, "⚠️ هشدار:\n\n")
    if text.startswith(prefix):
        return text
    return prefix + (text or "")
