from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import PLAN_ADMIN_SECRET
from app.core.database import get_db
from app.models.user import User, PlanType
from app.services.auth import get_current_user
from app.services.plan import (
    get_user_plan_status,
    update_user_plan,
    get_plan_info,
    PLAN_LIMITS,
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
    """
    دریافت وضعیت پلن کاربر فعلی
    """
    status = get_user_plan_status(current_user, db)
    return PlanStatusResponse(**status)


@router.put("/update", response_model=PlanStatusResponse)
def update_my_plan(
    payload: UpdatePlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_plan_admin_secret: str | None = Header(default=None),
):
    """
    تغییر پلن کاربر — فقط با PLAN_ADMIN_SECRET (هدر X-Plan-Admin-Secret).
    """
    if not PLAN_ADMIN_SECRET:
        raise HTTPException(
            status_code=403,
            detail="تغییر پلن از طریق API غیرفعال است",
        )
    if not x_plan_admin_secret or x_plan_admin_secret != PLAN_ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="مجوز تغییر پلن وجود ندارد")

    try:
        updated_user = update_user_plan(current_user, payload.plan_type, db)
        status = get_user_plan_status(updated_user, db)
        return PlanStatusResponse(**status)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"خطا در تغییر پلن: {str(e)}")


@router.get("/all", response_model=AllPlansResponse)
def get_all_plans():
    """
    دریافت لیست تمام پلن‌های موجود
    """
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
            )
        )
    return AllPlansResponse(plans=plans)
