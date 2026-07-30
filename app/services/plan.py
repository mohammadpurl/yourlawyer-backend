from datetime import date

from sqlalchemy.orm import Session

from app.core.config import (
    FREE_MONTHLY_QUESTION_CAP,
    FREE_USER_MONTHLY_COST_CAP,
    PAID_GOLD_MONTHLY_COST_CAP,
    PAID_SILVER_MONTHLY_COST_CAP,
)
from app.models.user import User, PlanType


PLAN_LIMITS = {
    PlanType.FREE: {
        "questions_per_month": FREE_MONTHLY_QUESTION_CAP,
        "name": "رایگان",
        "description": (
            f"پلن رایگان با حداکثر {FREE_MONTHLY_QUESTION_CAP} سوال در ماه "
            f"و سقف هزینه ${FREE_USER_MONTHLY_COST_CAP:.2f}؛ بدون آپلود سند"
        ),
        "allows_document_review": False,
    },
    PlanType.SILVER: {
        "questions_per_month": -1,  # unlimited count; USD cap applies
        "name": "نقره‌ای",
        "description": (
            f"پلن نقره‌ای با سقف هزینه ماهانه ${PAID_SILVER_MONTHLY_COST_CAP:.2f} "
            "و امکان بررسی/آپلود سند"
        ),
        "allows_document_review": True,
    },
    PlanType.GOLD: {
        "questions_per_month": -1,
        "name": "طلایی",
        "description": (
            f"پلن طلایی با سقف هزینه ماهانه ${PAID_GOLD_MONTHLY_COST_CAP:.2f} "
            "و امکان بررسی/آپلود سند"
        ),
        "allows_document_review": True,
    },
}


def get_plan_limit(plan_type: PlanType) -> int:
    return PLAN_LIMITS[plan_type]["questions_per_month"]


def get_plan_info(plan_type: PlanType) -> dict:
    return PLAN_LIMITS[plan_type]


def plan_allows_document_review(plan_type: PlanType | str) -> bool:
    if isinstance(plan_type, str):
        plan_type = PlanType(plan_type)
    return bool(PLAN_LIMITS[plan_type].get("allows_document_review"))


def cost_cap_for_plan(plan_type: PlanType | str) -> float:
    if isinstance(plan_type, str):
        plan_type = PlanType(plan_type)
    if plan_type == PlanType.FREE:
        return FREE_USER_MONTHLY_COST_CAP
    if plan_type == PlanType.SILVER:
        return PAID_SILVER_MONTHLY_COST_CAP
    if plan_type == PlanType.GOLD:
        return PAID_GOLD_MONTHLY_COST_CAP
    return FREE_USER_MONTHLY_COST_CAP


def reset_user_plan_if_needed(user: User, db: Session) -> None:
    today = date.today()
    if user.plan_reset_date is None or user.plan_reset_date < today:
        user.questions_used = 0
        if today.month == 12:
            user.plan_reset_date = date(today.year + 1, 1, 1)
        else:
            user.plan_reset_date = date(today.year, today.month + 1, 1)
        db.commit()


def check_user_can_ask_question(user: User, db: Session) -> tuple[bool, str]:
    """
    Legacy Q-count check. Prefer enforce_request_quota for full free/paid rules.
    Paid plans: always allow (USD capped elsewhere). Free: enforce question cap.
    """
    reset_user_plan_if_needed(user, db)
    plan_limit = get_plan_limit(user.plan_type)
    if plan_limit == -1:
        return True, ""
    if user.questions_used >= plan_limit:
        return False, (
            "شما به سقف ماهانه پلن رایگان رسیده‌اید. "
            "برای ادامه استفاده، اشتراک پولی تهیه کنید."
        )
    return True, ""


def increment_user_question_count(user: User, db: Session) -> None:
    reset_user_plan_if_needed(user, db)
    user.questions_used += 1
    db.commit()


def update_user_plan(user: User, new_plan: PlanType, db: Session) -> User:
    user.plan_type = new_plan
    user.questions_used = 0
    today = date.today()
    if today.month == 12:
        user.plan_reset_date = date(today.year + 1, 1, 1)
    else:
        user.plan_reset_date = date(today.year, today.month + 1, 1)
    db.commit()
    db.refresh(user)
    return user


def get_user_plan_status(user: User, db: Session) -> dict:
    reset_user_plan_if_needed(user, db)
    plan_info = get_plan_info(user.plan_type)
    plan_limit = get_plan_limit(user.plan_type)

    # Prefer Redis counters when available
    from app.services.quota import (
        get_user_cost_usd,
        get_user_question_count,
        get_system_free_cost_usd,
    )
    from app.core.config import SYSTEM_FREE_MONTHLY_CAP, SYSTEM_FREE_WARN_RATIO

    redis_q = get_user_question_count(user.id)
    questions_used = redis_q if redis_q > 0 else int(user.questions_used or 0)
    used_usd = get_user_cost_usd(user.id)
    cap = cost_cap_for_plan(user.plan_type)

    if plan_limit == -1:
        remaining: int | str = "نامحدود"
        questions_limit = None
    else:
        remaining = max(0, plan_limit - questions_used)
        questions_limit = plan_limit

    system_used = get_system_free_cost_usd()
    is_free = user.plan_type == PlanType.FREE

    return {
        "plan_type": user.plan_type.value,
        "plan_name": plan_info["name"],
        "plan_description": plan_info["description"],
        "questions_used": questions_used,
        "questions_limit": questions_limit,
        "questions_remaining": remaining,
        "plan_reset_date": (
            user.plan_reset_date.isoformat() if user.plan_reset_date else None
        ),
        "allows_document_review": plan_allows_document_review(user.plan_type),
        "cost_cap_usd": cap,
        "used_usd": used_usd,
        "remaining_usd": max(0.0, cap - used_usd),
        "system_free_near_limit": (
            is_free and system_used >= SYSTEM_FREE_MONTHLY_CAP * SYSTEM_FREE_WARN_RATIO
        ),
    }
