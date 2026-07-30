from pydantic import BaseModel, Field
from typing import Optional
from app.models.user import PlanType


class PlanStatusResponse(BaseModel):
    """وضعیت پلن کاربر + مصرف ماهانه"""

    plan_type: str
    plan_name: str
    plan_description: str
    questions_used: int
    questions_limit: Optional[int] = None
    questions_remaining: int | str  # عدد یا "نامحدود"
    plan_reset_date: Optional[str] = None
    allows_document_review: bool = False
    cost_cap_usd: Optional[float] = None
    used_usd: Optional[float] = None
    remaining_usd: Optional[float] = None
    system_free_near_limit: Optional[bool] = None


class UpdatePlanRequest(BaseModel):
    """درخواست تغییر پلن توسط ادمین (admin.manage)"""

    user_id: int = Field(..., description="شناسه کاربری که پلنش تغییر می‌کند")
    plan_type: PlanType = Field(..., description="نوع پلن جدید: free, silver, gold")


class PlanInfoResponse(BaseModel):
    """اطلاعات یک پلن"""

    plan_type: str
    name: str
    description: str
    questions_per_month: int | str
    cost_cap_usd: Optional[float] = None
    allows_document_review: bool = False


class AllPlansResponse(BaseModel):
    """لیست تمام پلن‌های موجود"""

    plans: list[PlanInfoResponse]
