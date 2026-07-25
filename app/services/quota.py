"""Monthly USD usage-quota with Redis atomic reserve / adjust / release."""

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
    QUOTA_ENABLED,
    QUOTA_DEFAULT_GLOBAL_USD,
    QUOTA_DEFAULT_USER_USD,
    QUOTA_FAIL_CLOSED,
)
from app.models.usage import UsageQuota, UsageLog
from app.models.user import User

logger = logging.getLogger(__name__)

Scope = Literal["global", "user"]

# Atomic: only increment if current + delta <= limit; set TTL on first write.
_RESERVE_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local delta = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
-- Compare in micro-USD integers to avoid float drift under concurrency
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


def quota_key(scope: Scope, identifier: str | int, period: str | None = None) -> str:
    period = period or current_period()
    return f"quota:{scope}:{identifier}:monthly:{period}"


def _require_redis():
    client = get_redis_client()
    if client is None:
        if QUOTA_FAIL_CLOSED:
            raise HTTPException(
                status_code=503,
                detail="سرویس محدودیت مصرف موقتاً در دسترس نیست. لطفاً بعداً تلاش کنید.",
            )
        return None
    return client


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
        max_cost_usd=Decimal(str(QUOTA_DEFAULT_GLOBAL_USD)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_or_create_user_quota(db: Session, user_id: int) -> UsageQuota:
    row = (
        db.query(UsageQuota)
        .filter(UsageQuota.scope == "user", UsageQuota.user_id == user_id)
        .first()
    )
    if row:
        return row
    row = UsageQuota(
        scope="user",
        user_id=user_id,
        max_cost_usd=Decimal(str(QUOTA_DEFAULT_USER_USD)),
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


def get_quota_status(db: Session, user: User | None = None) -> dict:
    period = current_period()
    global_q = get_or_create_global_quota(db)
    global_used = get_usage_usd("global", "system")
    result: dict = {
        "period": period,
        "global": {
            "max_cost_usd": float(global_q.max_cost_usd),
            "used_usd": global_used,
            "remaining_usd": max(0.0, float(global_q.max_cost_usd) - global_used),
        },
    }
    if user is not None:
        user_q = get_or_create_user_quota(db, user.id)
        user_used = get_usage_usd("user", user.id)
        result["user"] = {
            "user_id": user.id,
            "max_cost_usd": float(user_q.max_cost_usd),
            "used_usd": user_used,
            "remaining_usd": max(0.0, float(user_q.max_cost_usd) - user_used),
        }
    return result


def _try_reserve(
    client,
    key: str,
    amount: float,
    limit: float,
) -> bool:
    ttl = seconds_until_next_month()
    result = client.eval(_RESERVE_LUA, 1, key, str(amount), str(limit), str(ttl))
    return result != -1 and result is not None


def release_reservation(scope: Scope, identifier: str | int, amount: float) -> None:
    """Decrement reserved cost (rollback on OpenAI failure)."""
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
    """Correct Redis after real token usage is known."""
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
    Atomically reserve estimated USD against user + global monthly ceilings.
    Raises QuotaExceeded (mapped to HTTP 429 / 503 by callers).
    """
    if not QUOTA_ENABLED:
        return
    if estimated_usd <= 0:
        return

    client = _require_redis()
    if client is None:
        # fail-open when QUOTA_FAIL_CLOSED is false
        return

    global_q = get_or_create_global_quota(db)
    user_q = get_or_create_user_quota(db, user.id)
    g_key = quota_key("global", "system")
    u_key = quota_key("user", user.id)
    g_limit = float(global_q.max_cost_usd)
    u_limit = float(user_q.max_cost_usd)

    # Reserve user first, then global — release user if global fails
    if not _try_reserve(client, u_key, estimated_usd, u_limit):
        raise QuotaExceeded(
            "user",
            "سقف مصرف ماهانه شما به پایان رسیده است. لطفاً تا ابتدای ماه آینده صبر کنید یا با پشتیبانی تماس بگیرید.",
            429,
        )

    if not _try_reserve(client, g_key, estimated_usd, g_limit):
        release_reservation("user", user.id, estimated_usd)
        raise QuotaExceeded(
            "global",
            "سقف مصرف کلی سامانه در این ماه تکمیل شده است. سرویس موقتاً در دسترس نیست.",
            503,
        )


def check_quota_available(db: Session, user: User, estimated_usd: float = 0.01) -> None:
    """Pre-flight check used by FastAPI dependency (raises HTTPException)."""
    try:
        # Peek without permanently consuming: reserve tiny probe then release,
        # OR just read current usage. Prefer read-only check here.
        if not QUOTA_ENABLED:
            return
        client = _require_redis()
        if client is None:
            return

        global_q = get_or_create_global_quota(db)
        user_q = get_or_create_user_quota(db, user.id)
        g_used = get_usage_usd("global", "system")
        u_used = get_usage_usd("user", user.id)

        if u_used + estimated_usd > float(user_q.max_cost_usd):
            raise HTTPException(
                status_code=429,
                detail="سقف مصرف ماهانه شما به پایان رسیده است. لطفاً تا ابتدای ماه آینده صبر کنید یا با پشتیبانی تماس بگیرید.",
            )
        if g_used + estimated_usd > float(global_q.max_cost_usd):
            raise HTTPException(
                status_code=503,
                detail="سقف مصرف کلی سامانه در این ماه تکمیل شده است. سرویس موقتاً در دسترس نیست.",
            )
    except HTTPException:
        raise
    except QuotaExceeded as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


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
    """Aggregate current Redis usage for users that have a quota row."""
    period = period or current_period()
    rows = db.query(UsageQuota).filter(UsageQuota.scope == "user").all()
    out = []
    for row in rows:
        used = get_usage_usd("user", row.user_id)  # type: ignore[arg-type]
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
