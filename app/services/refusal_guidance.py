"""User-facing refusal messages + optional level-3 general guidance (no citations).

Level-3 must NEVER invent article numbers, dates, or case-specific legal holdings.
It only orients the user (domain / general law name / see a lawyer).

Frontend: when ``response_type == \"general_guidance\"``, show a distinct amber/
warning UI with label «راهنمایی کلی — بدون استناد به سند خاص». When
``response_type == \"refused\"``, show the refusal text without citation chrome.
``grounded`` answers keep the current citation UI.
See also ``docs/api_response_types.md``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import (
    DEFAULT_LLM_MODEL,
    ENABLE_GENERAL_GUIDANCE_FALLBACK,
    GENERAL_GUIDANCE_MIN_CLASSIFY_CONFIDENCE,
)

logger = logging.getLogger(__name__)

REFUSAL_USER_MESSAGES: dict[str, str] = {
    "no_chunks_retrieved": (
        "در حال حاضر منبع مرتبطی در پایگاه داده برای این موضوع یافت نشد. "
        "ممکن است این حوزه هنوز به‌طور کامل پوشش داده نشده باشد."
    ),
    "below_relevance_threshold": (
        "منابع بازیابی‌شده برای این سؤال به‌اندازه‌ی کافی مرتبط و دقیق نبودند. "
        "می‌توانید سؤال را با جزئیات بیشتر (مثلاً نام قانون یا مصوبه‌ی مرتبط) "
        "دوباره مطرح کنید."
    ),
    "out_of_domain": (
        "این سؤال خارج از حوزه‌های پوشش‌داده‌شده‌ی فعلی "
        "(مدنی، خانواده، کیفری، کار) به‌نظر می‌رسد."
    ),
    "below_confidence_threshold": (
        "اطمینان پاسخ کمتر از حد قابل‌اتکا بود؛ به‌جای ارائهٔ پاسخ مبهم، "
        "از دادن حکم مشخص خودداری شد."
    ),
    "llm_refused_despite_chunks": (
        "با وجود بازیابی چند منبع، محتوای آن‌ها برای پاسخ دقیق و مستند به این "
        "سؤال کافی تشخیص داده نشد."
    ),
    "empty_usable_context": (
        "متن قابل‌استفاده‌ای از منابع برای ساخت پاسخ مستند در دسترس نبود."
    ),
    "pipeline_error": (
        "به‌خاطر خطای فنی موقت امکان پاسخ‌گویی وجود نداشت. لطفاً دوباره تلاش کنید."
    ),
}

_DEFAULT_REFUSAL = (
    "در حال حاضر امکان ارائهٔ پاسخ مستند و قابل‌اتکا به این سؤال از روی "
    "منابع موجود فراهم نشد."
)

DOMAIN_DISPLAY_FA: dict[str, str] = {
    "مدنی": "حقوق مدنی",
    "خانواده": "حقوق خانواده",
    "کیفری": "حقوق کیفری",
    "کار_و_تامین_اجتماعی": "حقوق کار و تأمین اجتماعی",
    "تجاری_و_اسناد_تجاری": "حقوق تجاری و اسناد تجاری",
    "اداری": "حقوق اداری",
}

# Soft hints only — never presented as citations of a specific article.
DOMAIN_LAW_HINTS_FA: dict[str, str] = {
    "مدنی": "قانون مدنی جمهوری اسلامی ایران",
    "خانواده": "قوانین و مقررات حوزه خانواده",
    "کیفری": "قانون مجازات اسلامی و آیین دادرسی کیفری",
    "کار_و_تامین_اجتماعی": "قانون کار و قوانین تأمین اجتماعی",
    "تجاری_و_اسناد_تجاری": "قانون تجارت و مقررات اسناد تجاری",
    "اداری": "قوانین استخدامی و مقررات اداری",
}

GENERAL_GUIDANCE_DISCLAIMER = (
    "توجه: این یک راهنمایی کلی است و استناد به سند قانونی خاص نیست. "
    "برای تصمیم‌گیری درباره پروندهٔ خود با وکیل مشورت کنید."
)

GENERAL_GUIDANCE_SYSTEM_PROMPT = """
تو دستیار راهنمای اولیه‌ی یک پلتفرم حقوقی فارسی هستی. برای این سؤال، هیچ منبع
قانونی مشخصی در پایگاه داده پیدا نشده است. وظیفه‌ی تو **فقط** موارد زیر است:

۱. حوزه‌ی کلی حقوقی سؤال را نام ببر (مثلاً «این موضوع در حوزه‌ی حقوق کار است»)
۲. در صورت امکان، نام عمومی قانون یا نهاد مرتبط را ذکر کن (مثلاً «قانون کار جمهوری
   اسلامی ایران» یا «سازمان تأمین اجتماعی») — بدون ذکر شماره‌ی ماده یا حکم مشخص
۳. کاربر را به مشورت با وکیل یا مراجعه به منبع رسمی هدایت کن

**ممنوعیت‌های مطلق:**
- هرگز شماره‌ی ماده‌ی قانونی، تاریخ تصویب، یا متن حکم مشخص ذکر نکن — حتی اگر
  از دانش عمومی خودت مطمئن هستی، چون این ادعا بدون سند قابل‌اتکا نیست
- هرگز نگو «طبق قانون...» یا «قانون می‌گوید...» — این ادعای استناد به سند است
- هرگز پیش‌بینی نتیجه‌ی حقوقی یک وضعیت خاص نکن (مثلاً «شما مستحق X هستید»)
- پاسخ باید حداکثر ۳-۴ جمله باشد

سؤال کاربر: {query}
حوزه‌ی تشخیص‌داده‌شده: {domain}
راهنمای نرم (اختیاری، نه الزام به نقل ماده): {law_hint}
""".strip()

# Reject leaked article-style claims in model output
_ARTICLE_LEAK = re.compile(
    r"(ماده\s*[۰-۹0-9]+|تبصره\s*[۰-۹0-9]+|بند\s*[الف-یa-z]|طبق\s+قانون|قانون\s+می‌گوید|مستحق\s+هست)",
    re.IGNORECASE,
)


def domain_display_fa(taxonomy_domain: str | None) -> str | None:
    if not taxonomy_domain or taxonomy_domain in ("نامشخص", "unclassified", "None"):
        return None
    return DOMAIN_DISPLAY_FA.get(
        taxonomy_domain, taxonomy_domain.replace("_", " ")
    )


def format_refusal_user_message(
    refusal_reason: str | None,
    *,
    taxonomy_domain: str | None = None,
) -> str:
    """Build the user-visible refusal text (no LLM)."""
    reason = (refusal_reason or "").strip() or "empty_usable_context"
    base = REFUSAL_USER_MESSAGES.get(reason)
    if base is None:
        logger.warning("Unmapped refusal_reason=%r — using cautious default", reason)
        base = _DEFAULT_REFUSAL

    label = domain_display_fa(taxonomy_domain)
    if label and reason != "out_of_domain":
        return (
            f"سؤال شما در حوزه‌ی «{label}» تشخیص داده شد، ولی {base}"
        )
    return base


def should_offer_general_guidance(
    *,
    refusal_reason: str | None,
    taxonomy_domain: str | None,
    taxonomy_confidence: float | None,
) -> bool:
    if not ENABLE_GENERAL_GUIDANCE_FALLBACK:
        return False
    if refusal_reason not in {
        "no_chunks_retrieved",
        "below_relevance_threshold",
    }:
        return False
    if not taxonomy_domain or taxonomy_domain in ("نامشخص", "unclassified", ""):
        return False
    conf = float(taxonomy_confidence or 0.0)
    if conf < GENERAL_GUIDANCE_MIN_CLASSIFY_CONFIDENCE:
        return False
    return True


def _static_general_guidance(taxonomy_domain: str | None) -> str:
    label = domain_display_fa(taxonomy_domain) or "حقوقی مرتبط"
    hint = DOMAIN_LAW_HINTS_FA.get(taxonomy_domain or "", "منابع رسمی مربوط")
    return (
        f"این موضوع در حوزه‌ی «{label}» قرار می‌گیرد. "
        f"برای جزئیات، معمولاً به {hint} و مراجع رسمی همان حوزه مراجعه می‌شود. "
        f"{GENERAL_GUIDANCE_DISCLAIMER}"
    )


def _sanitize_guidance_text(text: str, taxonomy_domain: str | None) -> str:
    t = (text or "").strip()
    if not t or _ARTICLE_LEAK.search(t):
        logger.warning("General guidance rejected (empty or article leak); using static")
        return _static_general_guidance(taxonomy_domain)
    # Always append disclaimer if model omitted it
    if "راهنمایی کلی" not in t and "استناد به سند" not in t:
        t = f"{t}\n\n{GENERAL_GUIDANCE_DISCLAIMER}"
    return t


def generate_general_guidance(
    *,
    query: str,
    taxonomy_domain: str | None,
    user: Any | None = None,
    db: Any | None = None,
    request_id: str | None = None,
) -> str:
    """
    Short orientation text. Prefer LLM when quota path is available; else static.
    Never returns article numbers (sanitizer falls back to static).
    """
    label = domain_display_fa(taxonomy_domain) or (taxonomy_domain or "نامشخص")
    law_hint = DOMAIN_LAW_HINTS_FA.get(taxonomy_domain or "", "—")
    prompt = GENERAL_GUIDANCE_SYSTEM_PROMPT.format(
        query=query,
        domain=label,
        law_hint=law_hint,
    )

    from app.core.config import OPENAI_API_KEY

    if not OPENAI_API_KEY or user is None or db is None:
        return _static_general_guidance(taxonomy_domain)

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from app.services.llm import call_llm_with_quota_check

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(
                content="فقط راهنمایی کلی کوتاه بنویس؛ بدون ماده و بدون حکم مشخص."
            ),
        ]
        raw = call_llm_with_quota_check(
            messages=messages,
            user=user,
            db=db,
            model=DEFAULT_LLM_MODEL,
            pipeline_stage="general_guidance",
            max_completion_tokens=220,
            request_id=request_id,
            count_question=False,
        )
        return _sanitize_guidance_text(str(raw or ""), taxonomy_domain)
    except Exception as e:
        logger.warning("general_guidance LLM failed: %s — static fallback", e)
        return _static_general_guidance(taxonomy_domain)
