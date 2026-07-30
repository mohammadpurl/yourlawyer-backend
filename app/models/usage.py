"""Usage quota and cost-logging models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UsageQuota(Base):
    """Configurable cost ceilings (global or per-user), in USD per month."""

    __tablename__ = "usage_quotas"
    __table_args__ = (
        UniqueConstraint("scope", "user_id", name="uq_usage_quotas_scope_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 'global' | 'user'
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    max_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])


class UsageLog(Base):
    """Permanent audit log of LLM token usage and USD cost."""

    __tablename__ = "usage_logs"
    __table_args__ = (
        Index("idx_usage_logs_user_time", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(
        String(36),
        default=lambda: str(uuid4()),
        nullable=False,
        index=True,
    )
    pipeline_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    # classify | rerank | generate
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    user = relationship("User", foreign_keys=[user_id])


class UserUsageMonthly(Base):
    """Per-user monthly product usage (questions, document reviews, USD cost)."""

    __tablename__ = "user_usage_monthly"
    __table_args__ = (
        UniqueConstraint("user_id", "year_month", name="uq_user_usage_monthly_user_ym"),
        Index("idx_user_usage_monthly_ym", "year_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_review_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])


class UsageEvent(Base):
    """Product-level usage events (qa / document_review)."""

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("idx_usage_events_user_time", "user_id", "created_at"),
        Index("idx_usage_events_ym", "year_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # qa | document_review
    model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    user = relationship("User", foreign_keys=[user_id])


class SystemUsageMonthly(Base):
    """Aggregate free-tier system cost for the month (paid users excluded)."""

    __tablename__ = "system_usage_monthly"
    __table_args__ = (
        UniqueConstraint("year_month", name="uq_system_usage_monthly_ym"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)
    total_free_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
