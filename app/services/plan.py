from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.user import User, PlanType


# تعریف محدودیت‌های هر پلن
PLAN_LIMITS = {
    PlanType.FREE: {
        "questions_per_month": 10,
        "name": "رایگان",
        "description": "پلن رایگان با محدودیت 10 سوال در ماه",
    },
    PlanType.SILVER: {
        "questions_per_month": 100,
        "name": "نقره‌ای",
        "description": "پلن نقره‌ای با محدودیت 100 سوال در ماه",
    },
    PlanType.GOLD: {
        "questions_per_month": -1,  # -1 یعنی نامحدود
        "name": "طلایی",
        "description": "پلن طلایی با سوالات نامحدود",
    },
}


def get_plan_limit(plan_type: PlanType) -> int:
    """دریافت محدودیت سوالات برای یک پلن"""
    return PLAN_LIMITS[plan_type]["questions_per_month"]


def get_plan_info(plan_type: PlanType) -> dict:
    """دریافت اطلاعات یک پلن"""
    return PLAN_LIMITS[plan_type]


def reset_user_plan_if_needed(user: User, db: Session) -> None:
    """
    بررسی و ریست کردن تعداد سوالات کاربر در صورت نیاز (مثلاً شروع ماه جدید)
    """
    today = date.today()

    # اگر plan_reset_date وجود ندارد یا تاریخ گذشته است، ریست کن
    if user.plan_reset_date is None or user.plan_reset_date < today:
        user.questions_used = 0
        # تنظیم تاریخ ریست به اول ماه بعد
        if today.month == 12:
            user.plan_reset_date = date(today.year + 1, 1, 1)
        else:
            user.plan_reset_date = date(today.year, today.month + 1, 1)
        db.commit()


def check_user_can_ask_question(user: User, db: Session) -> tuple[bool, str]:
    """
    بررسی اینکه آیا کاربر می‌تواند سوال بپرسد یا نه

    Returns:
        (can_ask: bool, message: str)
    """
    # ریست کردن در صورت نیاز
    reset_user_plan_if_needed(user, db)

    # بررسی پلن
    plan_limit = get_plan_limit(user.plan_type)

    # اگر پلن طلایی است (نامحدود)
    if plan_limit == -1:
        return True, ""

    # بررسی محدودیت
    if user.questions_used >= plan_limit:
        plan_info = get_plan_info(user.plan_type)
        reset_date = user.plan_reset_date or date.today()
        return False, (
            f"شما به محدودیت سوالات پلن {plan_info['name']} رسیده‌اید. "
            f"می‌توانید در تاریخ {reset_date.strftime('%Y/%m/%d')} دوباره سوال بپرسید. "
            f"یا می‌توانید به پلن بالاتر ارتقا دهید."
        )

    return True, ""


def increment_user_question_count(user: User, db: Session) -> None:
    """افزایش تعداد سوالات استفاده شده توسط کاربر"""
    reset_user_plan_if_needed(user, db)
    user.questions_used += 1
    db.commit()


def update_user_plan(user: User, new_plan: PlanType, db: Session) -> User:
    """
    تغییر پلن کاربر

    Args:
        user: کاربر
        new_plan: پلن جدید
        db: session دیتابیس

    Returns:
        کاربر به‌روز شده
    """
    user.plan_type = new_plan
    # ریست کردن تعداد سوالات استفاده شده
    user.questions_used = 0
    # تنظیم تاریخ ریست به اول ماه بعد
    today = date.today()
    if today.month == 12:
        user.plan_reset_date = date(today.year + 1, 1, 1)
    else:
        user.plan_reset_date = date(today.year, today.month + 1, 1)
    db.commit()
    db.refresh(user)
    return user


def get_user_plan_status(user: User, db: Session) -> dict:
    """
    دریافت وضعیت پلن کاربر

    Returns:
        dict شامل اطلاعات پلن و تعداد سوالات باقیمانده
    """
    reset_user_plan_if_needed(user, db)

    plan_info = get_plan_info(user.plan_type)
    plan_limit = get_plan_limit(user.plan_type)

    if plan_limit == -1:
        remaining = -1  # نامحدود
    else:
        remaining = max(0, plan_limit - user.questions_used)

    return {
        "plan_type": user.plan_type.value,
        "plan_name": plan_info["name"],
        "plan_description": plan_info["description"],
        "questions_used": user.questions_used,
        "questions_limit": plan_limit if plan_limit != -1 else None,
        "questions_remaining": remaining if remaining != -1 else "نامحدود",
        "plan_reset_date": (
            user.plan_reset_date.isoformat() if user.plan_reset_date else None
        ),
    }
