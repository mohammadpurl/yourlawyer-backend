"""
اسکریپت migration برای تنظیم پلن پیش‌فرض برای کاربران موجود در دیتابیس

این اسکریپت باید یک بار اجرا شود تا کاربران موجود در دیتابیس که فیلدهای پلن ندارند،
پلن رایگان دریافت کنند.
"""

import sys
from pathlib import Path

# اضافه کردن مسیر ریشه پروژه به sys.path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from datetime import date
from sqlalchemy.orm import Session
from app.core.database import get_db, engine
from app.models.user import User, PlanType


def migrate_user_plans():
    """تنظیم پلن پیش‌فرض برای کاربران موجود"""
    db: Session = next(get_db())

    try:
        # پیدا کردن کاربرانی که plan_type ندارند یا NULL است
        # در SQLAlchemy 2.0، باید از filter استفاده کنیم
        users_without_plan = (
            db.query(User)
            .filter(
                (User.plan_type == None) | (User.plan_reset_date == None)  # noqa: E711
            )
            .all()
        )

        # یا همه کاربران را بررسی کنیم و آنهایی که plan_reset_date ندارند را به‌روز کنیم
        all_users = db.query(User).all()
        updated_count = 0

        today = date.today()
        if today.month == 12:
            default_reset_date = date(today.year + 1, 1, 1)
        else:
            default_reset_date = date(today.year, today.month + 1, 1)

        for user in all_users:
            needs_update = False

            # اگر plan_type تنظیم نشده، آن را به FREE تنظیم کن
            if not hasattr(user, "plan_type") or user.plan_type is None:
                user.plan_type = PlanType.FREE
                needs_update = True

            # اگر questions_used تنظیم نشده، آن را به 0 تنظیم کن
            if not hasattr(user, "questions_used") or user.questions_used is None:
                user.questions_used = 0
                needs_update = True

            # اگر plan_reset_date تنظیم نشده، آن را تنظیم کن
            if not hasattr(user, "plan_reset_date") or user.plan_reset_date is None:
                user.plan_reset_date = default_reset_date
                needs_update = True

            if needs_update:
                updated_count += 1

        db.commit()
        print(f"✅ {updated_count} کاربر به‌روزرسانی شدند.")
        print(f"   - پلن پیش‌فرض: {PlanType.FREE.value}")
        print(f"   - تعداد سوالات استفاده شده: 0")
        print(f"   - تاریخ ریست: {default_reset_date}")

    except Exception as e:
        db.rollback()
        print(f"❌ خطا در migration: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("شروع migration پلن‌های کاربران...")
    migrate_user_plans()
    print("Migration با موفقیت انجام شد!")
