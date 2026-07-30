"""Central OpenAI/LangChain invocation with reserve-then-adjust quota control."""

from __future__ import annotations

import logging
from typing import Any, Sequence
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import OPENAI_API_KEY, DEFAULT_LLM_MODEL, QUOTA_ENABLED
from app.models.user import User, PlanType
from app.services.pricing import calculate_cost_usd, estimate_call_cost_usd
from app.services.quota import (
    QuotaExceeded,
    adjust_reservation,
    persist_usage_log,
    record_usage,
    release_reservation,
    reserve_cost,
)

logger = logging.getLogger(__name__)


def _is_free(user: User) -> bool:
    return user.plan_type == PlanType.FREE or (
        isinstance(user.plan_type, str) and user.plan_type == PlanType.FREE.value
    )


def _messages_to_text(messages: Sequence[BaseMessage | dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        if isinstance(m, BaseMessage):
            parts.append(str(m.content or ""))
        elif isinstance(m, dict):
            parts.append(str(m.get("content") or ""))
        else:
            parts.append(str(m))
    return "\n".join(parts)


def _extract_usage(response: AIMessage) -> tuple[int, int]:
    meta = getattr(response, "usage_metadata", None) or {}
    if meta:
        return int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0)

    resp_meta = getattr(response, "response_metadata", None) or {}
    usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
    return int(usage.get("prompt_tokens") or 0), int(
        usage.get("completion_tokens") or 0
    )


def call_llm_with_quota_check(
    *,
    messages: Sequence[BaseMessage | dict[str, Any]],
    user: User,
    db: Session,
    model: str | None = None,
    pipeline_stage: str = "generate",
    max_completion_tokens: int = 1024,
    temperature: float = 0,
    request_id: str | None = None,
    request_type: str = "qa",
    count_question: bool | None = None,
) -> str:
    """
    Single choke-point for billable OpenAI calls.

    Reserve-then-adjust:
      1) estimate + Redis INCR
      2) invoke model
      3) adjust to real cost / release on error
      4) persist usage_logs + product usage (question count on generate)
    """
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="سرویس مدل زبانی پیکربندی نشده است.",
        )

    model_name = model or DEFAULT_LLM_MODEL
    req_id = request_id or str(uuid4())
    prompt_text = _messages_to_text(messages)
    estimated = estimate_call_cost_usd(
        model_name, prompt_text, max_completion_tokens=max_completion_tokens
    )

    reserved_user = 0.0
    reserved_system = 0.0
    free_user = _is_free(user)
    # Count a product question once per ask (generate stage), not classify/rerank
    if count_question is None:
        count_question = pipeline_stage == "generate" and request_type == "qa"

    try:
        if QUOTA_ENABLED:
            reserve_cost(db, user, estimated)
            reserved_user = estimated
            if free_user:
                reserved_system = estimated

        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=max_completion_tokens,
        )
        lc_messages: list[BaseMessage] = []
        for m in messages:
            if isinstance(m, BaseMessage):
                lc_messages.append(m)
            elif isinstance(m, dict):
                role = (m.get("role") or "user").lower()
                content = str(m.get("content") or "")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=str(m)))

        response = llm.invoke(lc_messages)
        if not isinstance(response, AIMessage):
            text = str(response)
            prompt_tokens = max(1, len(prompt_text) // 2)
            completion_tokens = max(1, len(text) // 2)
        else:
            text = str(response.content or "")
            prompt_tokens, completion_tokens = _extract_usage(response)
            if prompt_tokens == 0 and completion_tokens == 0:
                prompt_tokens = max(1, len(prompt_text) // 2)
                completion_tokens = max(1, len(text) // 2)

        actual = calculate_cost_usd(model_name, prompt_tokens, completion_tokens)

        if QUOTA_ENABLED and reserved_user:
            adjust_reservation("user", user.id, reserved_user, actual)
            if reserved_system:
                adjust_reservation("global", "system", reserved_system, actual)
            reserved_user = 0.0
            reserved_system = 0.0

        try:
            persist_usage_log(
                db,
                user_id=user.id,
                request_id=req_id,
                pipeline_stage=pipeline_stage,
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=actual,
            )
        except Exception as e:
            logger.warning("Failed to persist usage log: %s", e)

        try:
            record_usage(
                db,
                user=user,
                cost_usd=actual,
                request_type=request_type,  # type: ignore[arg-type]
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                request_id=req_id,
                count_question=bool(count_question),
            )
        except Exception as e:
            logger.warning("Failed to record usage: %s", e)

        return text

    except QuotaExceeded as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except HTTPException:
        if reserved_user:
            release_reservation("user", user.id, reserved_user)
            if reserved_system:
                release_reservation("global", "system", reserved_system)
        raise
    except Exception:
        if reserved_user:
            release_reservation("user", user.id, reserved_user)
            if reserved_system:
                release_reservation("global", "system", reserved_system)
        logger.exception(
            "LLM call failed for user_id=%s stage=%s", user.id, pipeline_stage
        )
        raise


def call_pipeline_stage_with_quota(
    *,
    stage: str,
    messages: Sequence[BaseMessage | dict[str, Any]],
    user: User,
    db: Session,
    model: str | None = None,
    max_completion_tokens: int = 512,
    request_id: str | None = None,
) -> str:
    """Convenience wrapper so classify / rerank / generate share one entrypoint."""
    return call_llm_with_quota_check(
        messages=messages,
        user=user,
        db=db,
        model=model,
        pipeline_stage=stage,
        max_completion_tokens=max_completion_tokens,
        request_id=request_id,
        count_question=(stage == "generate"),
    )
