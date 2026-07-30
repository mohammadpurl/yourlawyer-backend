from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_admin_manage
from app.models.user import User, PlanType
from app.services.auth import get_current_user
from app.services.plan import (
    get_user_plan_status,
    update_user_plan,
    get_plan_info,
    cost_cap_for_plan,
    plan_allows_document_review,
)
from app.schemas.plan import (
    PlanStatusResponse,
    UpdatePlanRequest,
    PlanInfoResponse,
    AllPlansResponse,
)

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/status", response_model=PlanStatusResponse)
def get_my_plan_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """دریافت وضعیت پلن کاربر فعلی"""
    status = get_user_plan_status(current_user, db)
    return PlanStatusResponse(**status)


@router.put("/update", response_model=PlanStatusResponse)
def update_user_plan_admin(
    payload: UpdatePlanRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_manage),
):
    """
    تغییر پلن یک کاربر — فقط با permission ``admin.manage`` (کاربر is_admin).
    بدون secret header موازی.
    """
    target = db.query(User).filter(User.id == payload.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")

    try:
        updated_user = update_user_plan(target, payload.plan_type, db)
        status = get_user_plan_status(updated_user, db)
        return PlanStatusResponse(**status)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"خطا در تغییر پلن: {str(e)}")


@router.get("/all", response_model=AllPlansResponse)
def get_all_plans():
    """دریافت لیست تمام پلن‌های موجود"""
    plans = []
    for plan_type in PlanType:
        plan_info = get_plan_info(plan_type)
        limit = plan_info["questions_per_month"]
        plans.append(
            PlanInfoResponse(
                plan_type=plan_type.value,
                name=plan_info["name"],
                description=plan_info["description"],
                questions_per_month=limit if limit != -1 else "نامحدود",
                cost_cap_usd=cost_cap_for_plan(plan_type),
                allows_document_review=plan_allows_document_review(plan_type),
            )
        )
    return AllPlansResponse(plans=plans)
