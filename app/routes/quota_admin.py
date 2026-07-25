"""Admin endpoints for usage-quota management.

Requires JWT auth + permission ``admin.manage`` (user.is_admin).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_admin_manage
from app.models.user import User
from app.schemas.quota import (
    QuotaBucketStatus,
    QuotaLimitUpdate,
    QuotaStatusResponse,
    QuotaUpdateResponse,
    UserQuotaUpdate,
)
from app.services.auth import get_current_user
from app.services.quota import (
    get_quota_status,
    list_user_usage_for_period,
    set_quota_limit,
)

router = APIRouter(prefix="/admin/quotas", tags=["admin-quotas"])


@router.get("", response_model=QuotaStatusResponse)
def get_quotas_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    status = get_quota_status(db, user=None)
    users = [
        QuotaBucketStatus(
            user_id=u["user_id"],
            max_cost_usd=u["max_cost_usd"],
            used_usd=u["used_usd"],
            remaining_usd=u["remaining_usd"],
        )
        for u in list_user_usage_for_period(db, status["period"])
    ]
    return QuotaStatusResponse(
        period=status["period"],
        global_quota=QuotaBucketStatus(**status["global"]),
        users=users,
    )


@router.get("/me", response_model=QuotaStatusResponse)
def get_my_quota_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Any authenticated user can see their own + global remaining budget."""
    status = get_quota_status(db, user=current_user)
    return QuotaStatusResponse(
        period=status["period"],
        global_quota=QuotaBucketStatus(**status["global"]),
        user_quota=QuotaBucketStatus(**status["user"]),
    )


@router.put("/global", response_model=QuotaUpdateResponse)
def update_global_quota(
    payload: QuotaLimitUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    row = set_quota_limit(db, scope="global", max_cost_usd=payload.max_cost_usd)
    return QuotaUpdateResponse(
        scope="global",
        max_cost_usd=float(row.max_cost_usd),
    )


@router.put("/users/{user_id}", response_model=QuotaUpdateResponse)
def update_user_quota(
    user_id: int,
    payload: QuotaLimitUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    row = set_quota_limit(
        db, scope="user", user_id=user_id, max_cost_usd=payload.max_cost_usd
    )
    return QuotaUpdateResponse(
        scope="user",
        user_id=user_id,
        max_cost_usd=float(row.max_cost_usd),
    )


@router.put("/users", response_model=QuotaUpdateResponse)
def update_user_quota_body(
    payload: UserQuotaUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    row = set_quota_limit(
        db,
        scope="user",
        user_id=payload.user_id,
        max_cost_usd=payload.max_cost_usd,
    )
    return QuotaUpdateResponse(
        scope="user",
        user_id=payload.user_id,
        max_cost_usd=float(row.max_cost_usd),
    )
