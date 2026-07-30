"""Admin dashboard read-only stats (users, usage, logins)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import SYSTEM_FREE_MONTHLY_CAP
from app.core.database import get_db
from app.core.permissions import require_admin_manage
from app.core.privacy import mask_mobile
from app.core.rate_limit import limiter
from app.models.login_history import LoginHistory
from app.models.usage import UsageEvent, UsageLog, SystemUsageMonthly
from app.models.user import User
from app.services.quota import current_period

router = APIRouter(prefix="/admin/stats", tags=["admin-stats"])


class ActiveUsersStats(BaseModel):
    daily: int
    weekly: int
    monthly: int
    total_users: int


class DailyUsagePoint(BaseModel):
    date: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class UsageTotals(BaseModel):
    period: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    free_system_cost_usd: float
    system_free_cap_usd: float
    daily: list[DailyUsagePoint]


class UserUsageRow(BaseModel):
    user_id: int
    mobile_masked: str
    plan_type: str
    question_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class UserUsageList(BaseModel):
    period: str
    users: list[UserUsageRow]


class LoginRow(BaseModel):
    id: int
    user_id: int | None
    mobile_masked: str
    ip: str | None
    success: bool
    created_at: str


class LoginList(BaseModel):
    items: list[LoginRow]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _period_start(days: int) -> datetime:
    return _utc_now() - timedelta(days=days)


@router.get("/users", response_model=ActiveUsersStats)
@limiter.limit("20/minute")
def admin_active_users(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    """Active users by distinct user_id in usage_logs over day/week/month."""
    now = _utc_now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def _count_since(since: datetime) -> int:
        return (
            db.query(func.count(func.distinct(UsageLog.user_id)))
            .filter(UsageLog.created_at >= since, UsageLog.user_id.isnot(None))
            .scalar()
            or 0
        )

    total_users = db.query(func.count(User.id)).scalar() or 0
    return ActiveUsersStats(
        daily=_count_since(day_ago),
        weekly=_count_since(week_ago),
        monthly=_count_since(month_ago),
        total_users=int(total_users),
    )


@router.get("/usage", response_model=UsageTotals)
@limiter.limit("20/minute")
def admin_usage_totals(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
    days: int = Query(30, ge=1, le=90),
):
    """System-wide token/cost totals + daily breakdown for charts."""
    period = current_period()
    since = _period_start(days)

    totals = (
        db.query(
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
            func.coalesce(func.sum(UsageLog.cost_usd), 0),
        )
        .filter(UsageLog.created_at >= since)
        .one()
    )
    prompt_t = int(totals[0] or 0)
    completion_t = int(totals[1] or 0)
    cost = float(totals[2] or 0)

    day_col = func.date(UsageLog.created_at)
    daily_rows = (
        db.query(
            day_col.label("d"),
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
            func.coalesce(func.sum(UsageLog.cost_usd), 0),
        )
        .filter(UsageLog.created_at >= since)
        .group_by(day_col)
        .order_by(day_col.asc())
        .all()
    )
    daily: list[DailyUsagePoint] = []
    for row in daily_rows:
        d = row[0]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        pt, ct, c = int(row[1] or 0), int(row[2] or 0), float(row[3] or 0)
        daily.append(
            DailyUsagePoint(
                date=date_str,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=pt + ct,
                cost_usd=round(c, 6),
            )
        )

    sys_row = (
        db.query(SystemUsageMonthly)
        .filter(SystemUsageMonthly.year_month == period)
        .first()
    )
    free_cost = float(sys_row.total_free_cost_usd) if sys_row else 0.0

    return UsageTotals(
        period=period,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        total_tokens=prompt_t + completion_t,
        cost_usd=round(cost, 6),
        free_system_cost_usd=round(free_cost, 6),
        system_free_cap_usd=SYSTEM_FREE_MONTHLY_CAP,
        daily=daily,
    )


@router.get("/usage-by-user", response_model=UserUsageList)
@limiter.limit("20/minute")
def admin_usage_by_user(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
    limit: int = Query(50, ge=1, le=200),
):
    """Top users by cost this calendar month (mobile always masked)."""
    period = current_period()
    # Month start UTC approximate from period YYYY-MM
    year, month = map(int, period.split("-"))
    month_start = datetime(year, month, 1)

    # Prefer usage_logs for tokens/cost (all pipeline stages)
    rows = (
        db.query(
            UsageLog.user_id,
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
            func.coalesce(func.sum(UsageLog.cost_usd), 0),
        )
        .filter(UsageLog.created_at >= month_start, UsageLog.user_id.isnot(None))
        .group_by(UsageLog.user_id)
        .order_by(func.sum(UsageLog.cost_usd).desc())
        .limit(limit)
        .all()
    )

    # Question counts from usage_events
    q_map: dict[int, int] = {}
    if rows:
        user_ids = [r[0] for r in rows]
        q_rows = (
            db.query(UsageEvent.user_id, func.count(UsageEvent.id))
            .filter(
                UsageEvent.user_id.in_(user_ids),
                UsageEvent.year_month == period,
                UsageEvent.request_type == "qa",
            )
            .group_by(UsageEvent.user_id)
            .all()
        )
        q_map = {int(uid): int(c) for uid, c in q_rows}

    users_out: list[UserUsageRow] = []
    for uid, pt, ct, cost in rows:
        user = db.query(User).filter(User.id == uid).first()
        users_out.append(
            UserUsageRow(
                user_id=int(uid),
                mobile_masked=mask_mobile(user.mobile if user else None),
                plan_type=user.plan_type.value if user else "unknown",
                question_count=q_map.get(int(uid), 0),
                prompt_tokens=int(pt or 0),
                completion_tokens=int(ct or 0),
                total_tokens=int(pt or 0) + int(ct or 0),
                cost_usd=round(float(cost or 0), 6),
            )
        )

    return UserUsageList(period=period, users=users_out)


@router.get("/logins", response_model=LoginList)
@limiter.limit("20/minute")
def admin_recent_logins(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
    limit: int = Query(100, ge=1, le=500),
):
    rows = (
        db.query(LoginHistory)
        .order_by(LoginHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return LoginList(
        items=[
            LoginRow(
                id=r.id,
                user_id=r.user_id,
                mobile_masked=r.mobile_masked,
                ip=r.ip,
                success=bool(r.success),
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
            for r in rows
        ]
    )
