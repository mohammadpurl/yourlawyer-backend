"""Payment list schemas for user profile."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PaymentItem(BaseModel):
    id: int
    amount: float
    currency: str
    status: str
    plan_type: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaymentListResponse(BaseModel):
    items: list[PaymentItem]
    total: int
