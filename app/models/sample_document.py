"""Sample document catalog (Solh library) — not ingested into legal Chroma."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SampleDocType(str, enum.Enum):
    CONTRACT = "contract"
    PETITION = "petition"
    POWER_OF_ATTORNEY = "power_of_attorney"
    COMPLAINT = "complaint"
    CONFIRMATION = "confirmation"
    DECLARATION = "declaration"
    COMPANY_STATUTE = "company_statute"
    PRISONER_REQUEST = "prisoner_request"


class SampleDocument(Base):
    __tablename__ = "sample_documents"
    __table_args__ = (
        UniqueConstraint("doc_type", "external_id", name="uq_sample_documents_type_ext"),
        Index("ix_sample_documents_title", "title"),
        Index("ix_sample_documents_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Relative to project data/ root, e.g. outputs_solh_contracts/10_....pdf
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true", index=True
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
