from pydantic import BaseModel, Field
from typing import Optional
from app.models.user import PlanType


class PlanStatusResponse(BaseModel):
    """وضعیت پلن کاربر"""

    plan_type: str
    plan_name: str
    plan_description: str
    questions_used: int
    questions_limit: Optional[int] = None
    questions_remaining: int | str  # می‌تواند عدد یا "نامحدود" باشد
    plan_reset_date: Optional[str] = None


class UpdatePlanRequest(BaseModel):
    """درخواست تغییر پلن"""

    plan_type: PlanType = Field(..., description="نوع پلن جدید: free, silver, gold")


class PlanInfoResponse(BaseModel):
    """اطلاعات یک پلن"""

    plan_type: str
    name: str
    description: str
    questions_per_month: int | str  # می‌تواند عدد یا "نامحدود" باشد


class AllPlansResponse(BaseModel):
    """لیست تمام پلن‌های موجود"""

    plans: list[PlanInfoResponse]
