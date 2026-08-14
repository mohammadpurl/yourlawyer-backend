"""Hierarchical Persian legal taxonomy — single source of truth for ingest + classify."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Living document: extend as rescrape coverage grows.
LEGAL_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "مدنی": {
        "اموال_و_مالکیت": [],
        "قراردادها_و_تعهدات": [],
        "مسئولیت_مدنی": ["ضمان قهری", "خسارت"],
        "ارث_و_وصیت": [],
        "ثبت_اسناد_و_املاک": [],
    },
    "خانواده": {
        "نکاح_و_طلاق": [],
        "مهریه_و_نفقه": [],
        "حضانت_و_ولایت": [],
        "فرزندخواندگی": [],
    },
    "کیفری": {
        "جرائم_عمومی": ["سرقت", "کلاهبرداری", "خیانت در امانت"],
        "حدود_قصاص_دیات": [],
        "تعزیرات": [],
        "آیین_دادرسی_کیفری": [],
        "جرائم_رایانه‌ای": [],
    },
    "تجاری_و_اسناد_تجاری": {
        "چک": ["برگشت چک", "صدور چک بلامحل", "ضمانت چک", "چک برگشتی", "قانون چک"],
        "سفته_و_برات": [],
        "شرکت‌های_تجاری": [],
        "ورشکستگی": [],
        "مالکیت_فکری": [],
    },
    "اداری": {
        "استخدام_کشوری": [],
        "دیوان_عدالت_اداری": [],
    },
    "کار_و_تامین_اجتماعی": {
        "قرارداد_کار": [],
        "بیمه_تامین_اجتماعی": [],
        "حوادث_ناشی_از_کار": [
            "حادثه ناشی از کار",
            "غرامت دستمزد",
            "ازکارافتادگی",
        ],
        "ایمنی_و_حفاظت_فنی": [
            "حفاظت فنی",
            "ایمنی کار",
            "وسایل ایمنی",
        ],
        "بیمه_مسئولیت_کارفرما": [
            "بیمه مسئولیت کارفرما",
            "بیمه اجباری کارگران ساختمانی",
        ],
    },
}

UNKNOWN_DOMAIN = "نامشخص"
UNKNOWN_SUBDOMAIN = None

# Heuristic cues for ingest / offline tagging (filename + content).
DOMAIN_CUES: dict[str, list[str]] = {
    "مدنی": [
        "مدنی",
        "مالکیت",
        "ملک",
        "قرارداد",
        "خرید و فروش",
        "اجاره",
        "وصیت",
        "ارث",
        "ثبت اسناد",
        "ضمان قهری",
    ],
    "خانواده": [
        "خانواده",
        "طلاق",
        "نکاح",
        "مهریه",
        "نفقه",
        "حضانت",
        "ولایت",
        "ازدواج",
    ],
    "کیفری": [
        "کیفری",
        "مجازات",
        "قتل",
        "جرم",
        "زندان",
        "حبس",
        "استرداد مجرم",
        "قصاص",
        "دیه",
        "تعزیر",
        "دادستان",
        "معاهده استرداد",
    ],
    "تجاری_و_اسناد_تجاری": [
        "تجارت",
        "تجاری",
        "چک",
        "سفته",
        "برات",
        "ورشکستگی",
        "شرکت سهامی",
    ],
    "اداری": ["دیوان عدالت", "استخدام کشوری", "اداری"],
    "کار_و_تامین_اجتماعی": [
        "قانون کار",
        "تامین اجتماعی",
        "کارگر",
        "کارفرما",
        "حادثه ناشی از کار",
        "ایمنی",
        "حفاظت فنی",
        "کارگاه",
        "ساختمان",
        "پیمانکار",
        "غرامت",
        "دیه کارگر",
        "بیمه مسئولیت",
        "کارگران ساختمانی",
    ],
}

SUBDOMAIN_CUES: dict[str, dict[str, list[str]]] = {
    "تجاری_و_اسناد_تجاری": {
        "چک": ["چک", "برگشت چک", "چک برگشتی", "صدور چک", "بلامحل", "صیاد"],
        "سفته_و_برات": ["سفته", "برات"],
        "شرکت‌های_تجاری": ["شرکت سهامی", "با مسئولیت محدود", "شرکت تجاری"],
        "ورشکستگی": ["ورشکستگی", "تصفیه"],
        "مالکیت_فکری": ["مالکیت فکری", "اختراع", "علامت تجاری"],
    },
    "خانواده": {
        "نکاح_و_طلاق": ["طلاق", "نکاح", "ازدواج", "عده"],
        "مهریه_و_نفقه": ["مهریه", "نفقه"],
        "حضانت_و_ولایت": ["حضانت", "ولایت"],
        "فرزندخواندگی": ["فرزندخواندگی", "فرزند خواندگی"],
    },
    "کیفری": {
        "جرائم_عمومی": ["سرقت", "کلاهبرداری", "خیانت در امانت"],
        "حدود_قصاص_دیات": ["قصاص", "دیه", "حد"],
        "تعزیرات": ["تعزیر"],
        "آیین_دادرسی_کیفری": ["آیین دادرسی کیفری", "آئين دادرسي كيفري"],
        "جرائم_رایانه‌ای": ["رایانه‌ای", "رايانه", "سایبری"],
    },
    "مدنی": {
        "اموال_و_مالکیت": ["مالکیت", "اموال"],
        "قراردادها_و_تعهدات": ["قرارداد", "تعهد"],
        "مسئولیت_مدنی": ["مسئولیت مدنی", "ضمان قهری", "خسارت"],
        "ارث_و_وصیت": ["ارث", "وصیت"],
        "ثبت_اسناد_و_املاک": ["ثبت اسناد", "املاک"],
    },
    "اداری": {
        "استخدام_کشوری": ["استخدام"],
        "دیوان_عدالت_اداری": ["دیوان عدالت"],
    },
    "کار_و_تامین_اجتماعی": {
        "قرارداد_کار": ["قرارداد کار", "کارگر", "کارفرما", "روابط کار"],
        "بیمه_تامین_اجتماعی": ["تامین اجتماعی", "بیمه تامین", "حق بیمه"],
        "حوادث_ناشی_از_کار": [
            "حادثه ناشی از کار",
            "حوادث ناشی از کار",
            "حادثه کار",
            "سقوط از ارتفاع",
            "غرامت",
            "ازکارافتادگی",
            "دیه کارگر",
        ],
        "ایمنی_و_حفاظت_فنی": [
            "حفاظت فنی",
            "ایمنی کار",
            "وسایل ایمنی",
            "تجهیزات ایمنی",
            "آیین نامه ایمنی",
            "کارگاه",
            "ساختمان",
            "پیمانکار",
        ],
        "بیمه_مسئولیت_کارفرما": [
            "بیمه مسئولیت کارفرما",
            "بیمه اجباری کارگران ساختمانی",
            "کارگران ساختمانی",
            "بیمه مسئولیت مدنی",
        ],
    },
}


def flatten_taxonomy() -> list[dict[str, str | None]]:
    """Flat list of (domain, subdomain) leaves for prompts / validation."""
    rows: list[dict[str, str | None]] = []
    for domain, subdomains in LEGAL_TAXONOMY.items():
        for subdomain, leaves in subdomains.items():
            rows.append({"domain": domain, "subdomain": subdomain})
            for leaf in leaves:
                rows.append({"domain": domain, "subdomain": subdomain, "leaf": leaf})
    return rows


def taxonomy_prompt_text() -> str:
    """Compact taxonomy text for LLM classify prompts."""
    lines: list[str] = []
    for domain, subdomains in LEGAL_TAXONOMY.items():
        lines.append(f"- {domain}:")
        for subdomain, leaves in subdomains.items():
            leaf_txt = f" ({', '.join(leaves)})" if leaves else ""
            lines.append(f"  - {subdomain}{leaf_txt}")
    return "\n".join(lines)


def is_valid_domain(domain: str | None) -> bool:
    return bool(domain) and domain in LEGAL_TAXONOMY


def is_valid_subdomain(domain: str | None, subdomain: str | None) -> bool:
    if not domain or not subdomain or domain not in LEGAL_TAXONOMY:
        return False
    return subdomain in LEGAL_TAXONOMY[domain]


def heuristic_tag_text(source: str, text: str) -> dict[str, Any]:
    """Rule-based domain/subdomain from filename + content snippet."""
    blob = f"{source}\n{(text or '')[:2500]}"
    domain_scores: dict[str, float] = {}
    for domain, cues in DOMAIN_CUES.items():
        score = sum(1.0 for c in cues if c in blob)
        if score:
            domain_scores[domain] = score

    if not domain_scores:
        return {
            "domain": UNKNOWN_DOMAIN,
            "subdomain": UNKNOWN_SUBDOMAIN,
            "confidence": 0.0,
            "method": "heuristic",
        }

    domain = max(domain_scores.items(), key=lambda x: x[1])[0]
    subdomain = UNKNOWN_SUBDOMAIN
    sub_scores: dict[str, float] = {}
    for sub, cues in SUBDOMAIN_CUES.get(domain, {}).items():
        score = sum(2.0 if len(c) > 3 else 1.0 for c in cues if c in blob)
        # Prefer exact leaf phrases from taxonomy
        for leaf in LEGAL_TAXONOMY.get(domain, {}).get(sub, []):
            if leaf in blob:
                score += 3.0
        if score:
            sub_scores[sub] = score
    if sub_scores:
        subdomain = max(sub_scores.items(), key=lambda x: x[1])[0]

    # Confidence: normalized heuristic
    top = domain_scores[domain]
    conf = min(0.95, 0.35 + 0.15 * top + (0.2 if subdomain else 0.0))
    return {
        "domain": domain,
        "subdomain": subdomain,
        "confidence": round(conf, 3),
        "method": "heuristic",
    }


# ---------------------------------------------------------------------------
# Query classify (LLM + heuristic + Redis) — single entry for RAG pipeline
# ---------------------------------------------------------------------------


def _cache_key(query: str) -> str:
    return hashlib.sha256((query or "").strip().encode("utf-8")).hexdigest()[:32]


def _get_cached(query: str) -> dict[str, Any] | None:
    try:
        from app.core.cache import cache_get

        return cache_get("classify:taxonomy", _cache_key(query))
    except Exception:
        return None


def _set_cached(query: str, result: dict[str, Any], ttl: int = 3600) -> None:
    try:
        from app.core.cache import cache_set

        cache_set("classify:taxonomy", result, ttl, _cache_key(query))
    except Exception:
        pass


def normalize_classify_result(raw: dict[str, Any]) -> dict[str, Any]:
    domain = raw.get("domain")
    subdomain = raw.get("subdomain")
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if domain in (None, "", "null", UNKNOWN_DOMAIN) or not is_valid_domain(str(domain)):
        return {
            "domain": None,
            "subdomain": None,
            "confidence": 0.0,
            "method": raw.get("method", "invalid"),
        }

    domain = str(domain)
    if subdomain in (None, "", "null"):
        subdomain = None
    elif not is_valid_subdomain(domain, str(subdomain)):
        subdomain = None
    else:
        subdomain = str(subdomain)

    return {
        "domain": domain,
        "subdomain": subdomain,
        "confidence": confidence,
        "method": raw.get("method", "llm"),
    }


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _llm_classify(query: str) -> dict[str, Any] | None:
    from app.core.config import (
        OPENAI_API_KEY,
        DEFAULT_LLM_MODEL,
        TAXONOMY_LLM_CLASSIFY,
    )

    if not OPENAI_API_KEY or not TAXONOMY_LLM_CLASSIFY:
        return None
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        system = (
            "تو یک طبقه‌بند حقوقی هستی. کوئری کاربر را بر اساس taxonomy زیر "
            "طبقه‌بندی کن. فقط یک JSON معتبر خروجی بده، بدون هیچ متن اضافه:\n"
            '{"domain": "...", "subdomain": "...", "confidence": 0.0-1.0}\n'
            "اگر کوئری با هیچ‌کدام از زیرشاخه‌ها تطبیق نداشت، subdomain را null بگذار "
            "و domain نزدیک‌ترین گزینه باشد.\n"
            f"Taxonomy:\n{taxonomy_prompt_text()}"
        )
        llm = ChatOpenAI(model=DEFAULT_LLM_MODEL or "gpt-4o-mini", temperature=0)
        resp = llm.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=f"کوئری: {query}"),
            ]
        )
        content = getattr(resp, "content", None) or str(resp)
        parsed = _parse_llm_json(content)
        parsed["method"] = "llm"
        return normalize_classify_result(parsed)
    except Exception as e:
        logger.warning("LLM taxonomy classify failed: %s", e)
        return None


def classify_query(query: str) -> dict[str, Any]:
    """Map a user query onto LEGAL_TAXONOMY (LLM → heuristic → cache)."""
    q = (query or "").strip()
    if not q:
        return {
            "domain": None,
            "subdomain": None,
            "confidence": 0.0,
            "method": "empty",
        }

    cached = _get_cached(q)
    if cached:
        out = dict(cached)
        out["method"] = f"cache:{out.get('method', 'unknown')}"
        return out

    result = _llm_classify(q)
    if result is None:
        heur = heuristic_tag_text("", q)
        result = normalize_classify_result(
            {
                "domain": heur.get("domain"),
                "subdomain": heur.get("subdomain"),
                "confidence": heur.get("confidence", 0.0),
                "method": "heuristic",
            }
        )
        if result.get("domain") == UNKNOWN_DOMAIN or result.get("domain") is None:
            result = {
                "domain": None,
                "subdomain": None,
                "confidence": 0.0,
                "method": "heuristic",
            }

    _set_cached(q, result)
    return result


def classify_confident(query: str) -> dict[str, Any]:
    """classify_query + ``confident`` vs TAXONOMY_CLASSIFY_MIN_CONFIDENCE."""
    from app.core.config import TAXONOMY_CLASSIFY_MIN_CONFIDENCE

    result = classify_query(query)
    conf = float(result.get("confidence") or 0.0)
    result["confident"] = bool(
        result.get("domain") and conf >= TAXONOMY_CLASSIFY_MIN_CONFIDENCE
    )
    return result
