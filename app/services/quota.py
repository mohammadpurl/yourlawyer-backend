"""Monthly cost + question quota with Redis atomic reserve / adjust / release."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.cache import get_redis_client
from app.core.config import (
    FREE_MONTHLY_QUESTION_CAP,
    FREE_USER_MONTHLY_COST_CAP,
    QUOTA_ENABLED,
    QUOTA_DEFAULT_GLOBAL_USD,
    QUOTA_FAIL_CLOSED,
    QUOTA_REDIS_TTL_SECONDS,
    SYSTEM_FREE_MONTHLY_CAP,
    SYSTEM_FREE_WARN_RATIO,
)
from app.models.usage import (
    UsageQuota,
    UsageLog,
    UserUsageMonthly,
    UsageEvent,
    SystemUsageMonthly,
)
from app.models.user import User, PlanType
from app.services.plan import cost_cap_for_plan, plan_allows_document_review

logger = logging.getLogger(__name__)

Scope = Literal["global", "user"]
RequestType = Literal["qa", "document_review"]

MSG_FREE_UPLOAD = "بررسی سند فقط برای کاربران پولی در دسترس است. لطفاً اشتراک تهیه کنید."
MSG_FREE_CAP = (
    "شما به سقف ماهانه پلن رایگان رسیده‌اید. "
    "برای ادامه استفاده، اشتراک پولی تهیه کنید."
)
MSG_SYSTEM_FREE = "ظرفیت رایگان این ماه تمام شده است. لطفاً بعداً تلاش کنید یا اشتراک تهیه کنید."
MSG_PAID_CAP = "سقف مصرف ماهانه پلن شما به پایان رسیده است. لطفاً تا ماه بعد صبر کنید یا پلن بالاتر تهیه کنید."

# Atomic: only increment if current + delta <= limit; set TTL on first write.
_RESERVE_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local delta = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local cur_i = math.floor(current * 1000000 + 0.5)
local delta_i = math.floor(delta * 1000000 + 0.5)
local limit_i = math.floor(limit * 1000000 + 0.5)
if (cur_i + delta_i) > limit_i then
  return -1
end
local newv = redis.call('INCRBYFLOAT', KEYS[1], delta)
if redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ttl)
end
return newv
"""


@dataclass
class QuotaStatus:
    scope: str
    identifier: str
    period: str
    used_usd: float
    max_usd: float
    remaining_usd: float


class QuotaExceeded(Exception):
    def __init__(self, scope: Scope, message: str, status_code: int):
        self.scope = scope
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def seconds_until_next_month() -> int:
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return max(60, int((nxt - now).total_seconds()) + 3600)


def _ttl() -> int:
    return max(QUOTA_REDIS_TTL_SECONDS, seconds_until_next_month())


def user_cost_key(user_id: int | str, period: str | None = None) -> str:
    period = period or current_period()
    return f"quota:user:{user_id}:{period}:cost_usd"


def user_question_key(user_id: int | str, period: str | None = None) -> str:
    period = period or current_period()
    return f"quota:user:{user_id}:{period}:question_count"


def system_free_cost_key(period: str | None = None) -> str:
    period = period or current_period()
    return f"quota:system:{period}:free_cost_usd"


def system_free_warn_key(period: str | None = None) -> str:
    period = period or current_period()
    return f"quota:system:{period}:free_warn_sent"


def quota_key(scope: Scope, identifier: str | int, period: str | None = None) -> str:
    """Back-compat helper used by tests / admin; maps to new key shapes."""
    period = period or current_period()
    if scope == "user":
        return user_cost_key(identifier, period)
    return system_free_cost_key(period)


def _require_redis():
    client = get_redis_client()
    if client is None:
        if QUOTA_FAIL_CLOSED:
            # Distinguish disabled Redis vs connection failure for clearer UX
            from app.core.config import REDIS_ENABLED

            if not REDIS_ENABLED:
                detail = (
                    "سرویس محدودیت مصرف فعال است ولی Redis غیرفعال است. "
                    "لطفاً REDIS_ENABLED=true را در تنظیمات قرار دهید."
                )
            else:
                detail = (
                    "سرویس محدودیت مصرف موقتاً در دسترس نیست. "
                    "لطفاً بعداً تلاش کنید."
                )
            raise HTTPException(status_code=503, detail=detail)
        return None
    return client


def _is_free(user: User) -> bool:
    return user.plan_type == PlanType.FREE or (
        isinstance(user.plan_type, str) and user.plan_type == PlanType.FREE.value
    )


def get_or_create_global_quota(db: Session) -> UsageQuota:
    row = (
        db.query(UsageQuota)
        .filter(UsageQuota.scope == "global", UsageQuota.user_id.is_(None))
        .first()
    )
    if row:
        return row
    row = UsageQuota(
        scope="global",
        user_id=None,
        max_cost_usd=Decimal(str(SYSTEM_FREE_MONTHLY_CAP or QUOTA_DEFAULT_GLOBAL_USD)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_or_create_user_quota(db: Session, user_id: int, plan_type: PlanType | None = None) -> UsageQuota:
    row = (
        db.query(UsageQuota)
        .filter(UsageQuota.scope == "user", UsageQuota.user_id == user_id)
        .first()
    )
    cap = cost_cap_for_plan(plan_type) if plan_type is not None else FREE_USER_MONTHLY_COST_CAP
    if row:
        # Keep DB ceiling aligned with current plan caps when possible
        if plan_type is not None and float(row.max_cost_usd) != cap:
            row.max_cost_usd = Decimal(str(cap))
            db.commit()
            db.refresh(row)
        return row
    row = UsageQuota(
        scope="user",
        user_id=user_id,
        max_cost_usd=Decimal(str(cap)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_usage_usd(scope: Scope, identifier: str | int) -> float:
    client = get_redis_client()
    if not client:
        return 0.0
    val = client.get(quota_key(scope, identifier))
    return float(val) if val is not None else 0.0


def get_user_cost_usd(user_id: int) -> float:
    client = get_redis_client()
    if not client:
        return 0.0
    val = client.get(user_cost_key(user_id))
    return float(val) if val is not None else 0.0


def get_user_question_count(user_id: int) -> int:
    client = get_redis_client()
    if not client:
        return 0
    val = client.get(user_question_key(user_id))
    return int(float(val)) if val is not None else 0


def get_system_free_cost_usd() -> float:
    client = get_redis_client()
    if not client:
        return 0.0
    val = client.get(system_free_cost_key())
    return float(val) if val is not None else 0.0


def get_quota_status(db: Session, user: User | None = None) -> dict:
    period = current_period()
    system_used = get_system_free_cost_usd()
    result: dict = {
        "period": period,
        "global": {
            "max_cost_usd": SYSTEM_FREE_MONTHLY_CAP,
            "used_usd": system_used,
            "remaining_usd": max(0.0, SYSTEM_FREE_MONTHLY_CAP - system_used),
        },
        "system_free": {
            "max_cost_usd": SYSTEM_FREE_MONTHLY_CAP,
            "used_usd": system_used,
            "remaining_usd": max(0.0, SYSTEM_FREE_MONTHLY_CAP - system_used),
            "near_limit": system_used >= SYSTEM_FREE_MONTHLY_CAP * SYSTEM_FREE_WARN_RATIO,
        },
    }
    if user is not None:
        cap = cost_cap_for_plan(user.plan_type)
        user_used = get_user_cost_usd(user.id)
        q_used = get_user_question_count(user.id)
        q_limit = FREE_MONTHLY_QUESTION_CAP if _is_free(user) else None
        result["user"] = {
            "user_id": user.id,
            "plan_type": user.plan_type.value if hasattr(user.plan_type, "value") else str(user.plan_type),
            "max_cost_usd": cap,
            "used_usd": user_used,
            "remaining_usd": max(0.0, cap - user_used),
            "questions_used": q_used,
            "questions_limit": q_limit,
            "system_free_near_limit": (
                _is_free(user)
                and system_used >= SYSTEM_FREE_MONTHLY_CAP * SYSTEM_FREE_WARN_RATIO
            ),
        }
    return result


def _try_reserve(client, key: str, amount: float, limit: float) -> bool:
    result = client.eval(_RESERVE_LUA, 1, key, str(amount), str(limit), str(_ttl()))
    return result != -1 and result is not None


def _ensure_ttl(client, key: str) -> None:
    try:
        if client.ttl(key) < 0:
            client.expire(key, _ttl())
    except Exception:
        pass


def release_reservation(scope: Scope, identifier: str | int, amount: float) -> None:
    if amount <= 0:
        return
    client = get_redis_client()
    if not client:
        return
    key = quota_key(scope, identifier)
    try:
        client.incrbyfloat(key, -abs(amount))
    except Exception as e:
        logger.warning("Failed to release quota reservation %s: %s", key, e)


def adjust_reservation(
    scope: Scope, identifier: str | int, reserved: float, actual: float
) -> None:
    delta = actual - reserved
    if abs(delta) < 1e-12:
        return
    client = get_redis_client()
    if not client:
        return
    key = quota_key(scope, identifier)
    try:
        client.incrbyfloat(key, delta)
    except Exception as e:
        logger.warning("Failed to adjust quota %s: %s", key, e)


def reserve_cost(db: Session, user: User, estimated_usd: float) -> None:
    """
    Atomically reserve estimated USD against user plan cap.
    Free users also reserve against the shared system free pool.
    """
    if not QUOTA_ENABLED:
        return
    if estimated_usd <= 0:
        return

    client = _require_redis()
    if client is None:
        return

    plan = getattr(user, "plan_type", PlanType.FREE)
    u_limit = cost_cap_for_plan(plan)
    # Keep UsageQuota row in sync for admin tooling
    get_or_create_user_quota(db, user.id, plan if isinstance(plan, PlanType) else PlanType(plan))

    u_key = user_cost_key(user.id)
    if not _try_reserve(client, u_key, estimated_usd, u_limit):
        raise QuotaExceeded(
            "user",
            MSG_FREE_CAP if _is_free(user) else MSG_PAID_CAP,
            429,
        )

    if _is_free(user):
        g_key = system_free_cost_key()
        if not _try_reserve(client, g_key, estimated_usd, SYSTEM_FREE_MONTHLY_CAP):
            release_reservation("user", user.id, estimated_usd)
            raise QuotaExceeded("global", MSG_SYSTEM_FREE, 503)


def check_quota_available(db: Session, user: User, estimated_usd: float = 0.01) -> None:
    """Pre-flight cost check (raises HTTPException)."""
    try:
        if not QUOTA_ENABLED:
            return
        client = _require_redis()
        if client is None:
            return

        cap = cost_cap_for_plan(user.plan_type)
        u_used = get_user_cost_usd(user.id)
        if u_used + estimated_usd > cap:
            raise HTTPException(
                status_code=429,
                detail=MSG_FREE_CAP if _is_free(user) else MSG_PAID_CAP,
            )
        if _is_free(user):
            g_used = get_system_free_cost_usd()
            if g_used + estimated_usd > SYSTEM_FREE_MONTHLY_CAP:
                raise HTTPException(status_code=503, detail=MSG_SYSTEM_FREE)
    except HTTPException:
        raise
    except QuotaExceeded as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


def enforce_request_quota(
    user: User,
    db: Session,
    request_type: RequestType = "qa",
) -> None:
    """
    Unit pre-check before ask / upload.
    Raises HTTPException with plan-aligned status codes.
    """
    if not QUOTA_ENABLED:
        # Still gate free uploads even if USD quota disabled
        if request_type == "document_review" and not plan_allows_document_review(
            user.plan_type
        ):
            raise HTTPException(status_code=403, detail=MSG_FREE_UPLOAD)
        return

    if request_type == "document_review" and not plan_allows_document_review(
        user.plan_type
    ):
        raise HTTPException(status_code=403, detail=MSG_FREE_UPLOAD)

    client = _require_redis()
    if client is None:
        return

    if _is_free(user):
        q_used = get_user_question_count(user.id)
        # Fallback to User.questions_used if Redis empty but DB has count
        if q_used == 0 and getattr(user, "questions_used", 0):
            q_used = int(user.questions_used)
        if request_type == "qa" and q_used >= FREE_MONTHLY_QUESTION_CAP:
            raise HTTPException(status_code=429, detail=MSG_FREE_CAP)

        u_used = get_user_cost_usd(user.id)
        if u_used >= FREE_USER_MONTHLY_COST_CAP:
            raise HTTPException(status_code=429, detail=MSG_FREE_CAP)

        g_used = get_system_free_cost_usd()
        if g_used >= SYSTEM_FREE_MONTHLY_CAP:
            raise HTTPException(status_code=503, detail=MSG_SYSTEM_FREE)
    else:
        cap = cost_cap_for_plan(user.plan_type)
        u_used = get_user_cost_usd(user.id)
        if u_used >= cap:
            raise HTTPException(status_code=429, detail=MSG_PAID_CAP)


def _maybe_warn_system_free(client, used: float) -> None:
    if used < SYSTEM_FREE_MONTHLY_CAP * SYSTEM_FREE_WARN_RATIO:
        return
    warn_key = system_free_warn_key()
    try:
        # SET NX — one warning per month
        created = client.set(warn_key, "1", nx=True, ex=_ttl())
        if created:
            logger.warning(
                "System free monthly budget near/over %.0f%%: used=$%.4f cap=$%.2f period=%s",
                SYSTEM_FREE_WARN_RATIO * 100,
                used,
                SYSTEM_FREE_MONTHLY_CAP,
                current_period(),
            )
    except Exception as e:
        logger.debug("system free warn check failed: %s", e)


def record_usage(
    db: Session,
    *,
    user: User,
    cost_usd: float,
    request_type: RequestType = "qa",
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    request_id: str | None = None,
    count_question: bool = True,
) -> None:
    """
    After successful billable work: adjust Redis counters, persist events + monthly rows.
    Assumes Redis cost already reflects `actual` via adjust_reservation; this adds
    question/system increments and Postgres upserts.
    """
    period = current_period()
    client = get_redis_client()
    is_free = _is_free(user)

    if client and count_question and request_type == "qa":
        try:
            qkey = user_question_key(user.id, period)
            client.incr(qkey)
            _ensure_ttl(client, qkey)
        except Exception as e:
            logger.warning("Failed to incr question_count: %s", e)

    if client and is_free and cost_usd:
        # Cost already adjusted on user key; system free was reserved+adjusted in llm path.
        # Ensure warn fires based on current system usage.
        try:
            _maybe_warn_system_free(client, get_system_free_cost_usd())
        except Exception:
            pass

    # Sync User.questions_used from Redis when possible
    try:
        if count_question and request_type == "qa":
            from app.services.plan import reset_user_plan_if_needed

            reset_user_plan_if_needed(user, db)
            if client:
                user.questions_used = get_user_question_count(user.id)
            else:
                user.questions_used = int(user.questions_used or 0) + 1
            db.commit()
    except Exception as e:
        logger.warning("Failed to sync questions_used: %s", e)

    try:
        event = UsageEvent(
            user_id=user.id,
            year_month=period,
            request_type=request_type,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=Decimal(str(round(cost_usd, 6))),
            request_id=request_id,
        )
        db.add(event)

        monthly = (
            db.query(UserUsageMonthly)
            .filter(
                UserUsageMonthly.user_id == user.id,
                UserUsageMonthly.year_month == period,
            )
            .first()
        )
        if not monthly:
            monthly = UserUsageMonthly(
                user_id=user.id,
                year_month=period,
                question_count=0,
                document_review_count=0,
                total_cost_usd=Decimal("0"),
            )
            db.add(monthly)
            db.flush()

        if request_type == "qa" and count_question:
            monthly.question_count = int(monthly.question_count or 0) + 1
        if request_type == "document_review":
            monthly.document_review_count = int(monthly.document_review_count or 0) + 1
        monthly.total_cost_usd = Decimal(str(monthly.total_cost_usd or 0)) + Decimal(
            str(round(cost_usd, 6))
        )

        if is_free and cost_usd:
            sys_row = (
                db.query(SystemUsageMonthly)
                .filter(SystemUsageMonthly.year_month == period)
                .first()
            )
            if not sys_row:
                sys_row = SystemUsageMonthly(
                    year_month=period,
                    total_free_cost_usd=Decimal("0"),
                )
                db.add(sys_row)
                db.flush()
            sys_row.total_free_cost_usd = Decimal(
                str(sys_row.total_free_cost_usd or 0)
            ) + Decimal(str(round(cost_usd, 6)))

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Failed to persist usage event/monthly: %s", e)


def persist_usage_log(
    db: Session,
    *,
    user_id: int | None,
    request_id: str,
    pipeline_stage: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> UsageLog:
    row = UsageLog(
        user_id=user_id,
        request_id=request_id,
        pipeline_stage=pipeline_stage,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=Decimal(str(round(cost_usd, 6))),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_quota_limit(
    db: Session,
    *,
    scope: Scope,
    max_cost_usd: float,
    user_id: int | None = None,
) -> UsageQuota:
    if scope == "global":
        row = get_or_create_global_quota(db)
        row.max_cost_usd = Decimal(str(max_cost_usd))
    else:
        if user_id is None:
            raise ValueError("user_id required for user scope")
        row = get_or_create_user_quota(db, user_id)
        row.max_cost_usd = Decimal(str(max_cost_usd))
    db.commit()
    db.refresh(row)
    return row


def list_user_usage_for_period(db: Session, period: str | None = None) -> list[dict]:
    period = period or current_period()
    rows = db.query(UsageQuota).filter(UsageQuota.scope == "user").all()
    out = []
    for row in rows:
        used = get_user_cost_usd(row.user_id)  # type: ignore[arg-type]
        out.append(
            {
                "user_id": row.user_id,
                "period": period,
                "max_cost_usd": float(row.max_cost_usd),
                "used_usd": used,
                "remaining_usd": max(0.0, float(row.max_cost_usd) - used),
            }
        )
    return out


def ensure_default_quotas(db: Session) -> None:
    get_or_create_global_quota(db)
