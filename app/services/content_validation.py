"""Lightweight title/content validation for legal document ingestion.

Prevents known cross-contamination patterns (e.g. «برنامه هفتم» body under an
unrelated law filename) without rejecting the wider corpus.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR

# Keep in sync with scripts/audit_content_title_mismatch.py EXPECTED_KEYWORDS
EXPECTED_KEYWORDS: dict[str, list[str]] = {
    "قانون مدنی": ["نکاح", "طلاق", "مهر", "ماده 1133", "ماده ۱۱۳۳", "عقد"],
    "قانون مدني": ["نکاح", "طلاق", "مهر", "ماده 1133", "ماده ۱۱۳۳", "عقد"],
    "قانون حمایت خانواده": [
        "دادگاه خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
        "حضانت",
    ],
    "قانون حمايت خانواده": [
        "دادگاه خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
        "حضانت",
    ],
    "آیین دادرسی مدنی": ["دادگاه", "خواهان", "خوانده", "دادخواست"],
    "آيين دادرسي مدني": ["دادگاه", "خواهان", "خوانده", "دادخواست"],
    "آئين دادرسي مدني": ["دادگاه", "خواهان", "خوانده", "دادخواست"],
    "محکومیت های مالی": ["محکوم", "دین", "اعسار", "حبس"],
    "محكوميت هاي مالي": ["محکوم", "دین", "اعسار", "حبس"],
    "اجرای احکام مدنی": ["محکوم‌علیه", "محکوم عليه", "اجرائیه", "اجرائيه", "دادورز"],
    "اجراي احكام مدني": ["محکوم‌علیه", "محکوم عليه", "اجرائیه", "اجرائيه", "دادورز"],
    "قانون کار": ["کارگر", "کارفرما", "قرارداد کار"],
    "قانون كار": ["کارگر", "کارفرما", "قرارداد کار"],
    "قانون مجازات": ["مجازات", "حبس", "جزای نقدی", "جزاي نقدي"],
    "قانون تجارت": ["تاجر", "برات", "شرکت", "شركت"],
    "آیین‌نامه اجرایی قانون حمایت خانواده": [
        "مرکز مشاوره خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
    ],
    "آيين نامه اجرايي قانون حمايت خانواده": [
        "مرکز مشاوره خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
    ],
    "آیین نامه اجرایی قانون حمایت خانواده": [
        "مرکز مشاوره خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
    ],
}

CONTAMINATION_MARKERS = [
    "برنامه هفتم",
    "برنامه پنجساله هفتم",
    "برنامه پيشرفت",
    "برنامه پیشرفت",
]

REJECTED_LOG = Path(BASE_DIR) / "storage" / "ingestion_rejected.json"


def _norm(text: str) -> str:
    return (
        (text or "")
        .replace("\u200c", " ")
        .replace("ي", "ی")
        .replace("ك", "ک")
    )


def match_expected_title(source: str) -> tuple[str, list[str]] | None:
    blob = _norm(source)
    for key in sorted(EXPECTED_KEYWORDS.keys(), key=len, reverse=True):
        if _norm(key) in blob:
            return key, EXPECTED_KEYWORDS[key]
    return None


def _has_any(text: str, needles: list[str]) -> bool:
    n = _norm(text)
    return any(_norm(x) in n for x in needles)


def validate_document_content(source: str, content: str) -> tuple[bool, str | None]:
    """Return (ok, reject_reason). Unknown titles always pass."""
    matched = match_expected_title(source)
    if not matched:
        return True, None

    key, keywords = matched
    # Title itself is برنامه هفتم — allow
    if "برنامه هفتم" in _norm(source) or "برنامه پنجساله هفتم" in _norm(source):
        return True, None

    # Cross-contamination: any برنامه هفتم marker under a different known law title
    if _has_any(content, CONTAMINATION_MARKERS):
        return (
            False,
            f"cross_contamination: source matched '{key}' but body contains برنامه هفتم markers",
        )

    if not _has_any(content, keywords):
        return (
            False,
            f"title_keyword_mismatch: source matched '{key}' but none of {keywords} "
            f"found in extracted content",
        )

    return True, None


def append_rejection(record: dict[str, Any]) -> None:
    REJECTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing: list[Any] = []
    if REJECTED_LOG.exists():
        try:
            existing = json.loads(REJECTED_LOG.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []
    record = {
        **record,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
    }
    existing.append(record)
    REJECTED_LOG.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
