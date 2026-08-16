"""Pre-RAG intent detection (short-circuit non-legal messages).

Fail-open: on LLM/cache errors, return ``legal_question`` so real legal asks
are never blocked by this stage.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.cache import cache_get, cache_set
from app.core.config import (
    DEFAULT_LLM_MODEL,
    ENABLE_INTENT_DETECTION,
    INTENT_CACHE_TTL_SECONDS,
    OPENAI_API_KEY,
)
from app.services.canned_responses import get_canned_response

logger = logging.getLogger(__name__)

IntentLabel = Literal[
    "legal_question",
    "meta_capability",
    "greeting_chitchat",
    "out_of_scope",
]

VALID_INTENTS: frozenset[str] = frozenset(
    {
        "legal_question",
        "meta_capability",
        "greeting_chitchat",
        "out_of_scope",
    }
)

INTENT_SYSTEM_PROMPT = """
تو طبقه‌بند نیت پیام کاربر برای یک دستیار حقوقی فارسی هستی.
فقط یکی از این چهار برچسب را در JSON برگردان — بدون هیچ متن اضافه:

{"intent":"<label>","confidence":0.0-1.0}

برچسب‌ها:
- legal_question: سؤال حقوقی واقعی که نیاز به جستجو در قوانین/مقررات دارد
  (مثلاً شرایط طلاق، حقوق کارگر، تعریف جرم، مهریه، حضانت، ماده فلان قانون)
- meta_capability: سؤال درباره توانایی‌ها/هویت سیستم یا درخواست تنظیم سند
  (شکواییه، دادخواست، لایحه، قرارداد، «می‌تونی بنویسی»، «چطور کار می‌کنی»،
  «وکیل هستی»، «چه کارهایی بلدی»)
- greeting_chitchat: سلام، خداحافظی، تشکر، شوخی یا گپ غیرحقوقی کوتاه
- out_of_scope: موضوع کاملاً غیرحقوقی (دستور پخت، برنامه‌نویسی، ورزش، …)
  که نه گپ کوتاه است و نه سؤال حقوقی

اگر مردد بودی بین legal_question و چیز دیگر، legal_question را انتخاب کن.
""".strip()


class IntentResult(BaseModel):
    intent: IntentLabel = "legal_question"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_model_response: str = ""


def _parse_intent_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _legal_question_fallback(raw: str = "", confidence: float = 0.0) -> IntentResult:
    return IntentResult(
        intent="legal_question",
        confidence=confidence,
        raw_model_response=raw,
    )


def _llm_detect(query: str) -> IntentResult:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    model = DEFAULT_LLM_MODEL or "gpt-4o-mini"
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        max_tokens=80,
    )
    resp = llm.invoke(
        [
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=f"پیام کاربر:\n{query}"),
        ]
    )
    raw = getattr(resp, "content", None) or str(resp)
    parsed = _parse_intent_json(str(raw))
    label = str(parsed.get("intent") or "").strip()
    conf = float(parsed.get("confidence") or 0.0)
    conf = max(0.0, min(1.0, conf))
    if label not in VALID_INTENTS:
        logger.warning("Intent detector unknown label=%r — fail-open legal_question", label)
        return _legal_question_fallback(raw=str(raw), confidence=conf)
    return IntentResult(intent=label, confidence=conf, raw_model_response=str(raw))  # type: ignore[arg-type]


def detect_intent(query: str) -> IntentResult:
    """Classify user intent. Fail-open to ``legal_question`` on any error."""
    q = (query or "").strip()
    if not q:
        return IntentResult(
            intent="greeting_chitchat",
            confidence=1.0,
            raw_model_response="",
        )

    if not ENABLE_INTENT_DETECTION:
        return IntentResult(
            intent="legal_question",
            confidence=1.0,
            raw_model_response="feature_flag_off",
        )

    cached = cache_get("intent", q)
    if isinstance(cached, dict) and cached.get("intent") in VALID_INTENTS:
        return IntentResult(
            intent=cached["intent"],
            confidence=float(cached.get("confidence") or 0.0),
            raw_model_response=str(cached.get("raw_model_response") or "cache_hit"),
        )

    if not OPENAI_API_KEY:
        logger.warning("Intent detector: no OPENAI_API_KEY — fail-open legal_question")
        return _legal_question_fallback(raw="no_api_key")

    t0 = time.perf_counter()
    try:
        result = _llm_detect(q)
    except Exception as e:
        logger.warning("Intent detector failed (fail-open legal_question): %s", e)
        return _legal_question_fallback(raw=f"error:{type(e).__name__}")

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "INTENT_DETECT %s",
        json.dumps(
            {
                "event": "INTENT_DETECT",
                "intent": result.intent,
                "confidence": result.confidence,
                "latency_ms": latency_ms,
                "query_preview": q[:120],
            },
            ensure_ascii=False,
        ),
    )

    try:
        cache_set(
            "intent",
            {
                "intent": result.intent,
                "confidence": result.confidence,
                "raw_model_response": result.raw_model_response[:500],
            },
            INTENT_CACHE_TTL_SECONDS,
            q,
        )
    except Exception:
        pass

    return result


def canned_payload_for_intent(intent: str) -> str:
    return get_canned_response(intent)
