"""Pydantic schemas for usage-quota admin API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QuotaLimitUpdate(BaseModel):
    max_cost_usd: float = Field(..., gt=0, description="سقف ماهانه به دلار")


class UserQuotaUpdate(BaseModel):
    user_id: int
    max_cost_usd: float = Field(..., gt=0)


class QuotaBucketStatus(BaseModel):
    max_cost_usd: float
    used_usd: float
    remaining_usd: float
    user_id: int | None = None


class QuotaStatusResponse(BaseModel):
    period: str
    global_quota: QuotaBucketStatus
    user_quota: QuotaBucketStatus | None = None
    users: list[QuotaBucketStatus] = []


class QuotaUpdateResponse(BaseModel):
    scope: Literal["global", "user"]
    user_id: int | None = None
    max_cost_usd: float
    message: str = "سقف با موفقیت به‌روزرسانی شد"
