"""Pydantic schemas for Solh sample-document library."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


DISCLAIMER_FA = (
    "این فایل صرفاً یک نمونه سند است و جایگزین مشاوره حقوقی نیست. "
    "پیش از استفاده، با وکیل یا مشاور حقوقی مشورت کنید."
)


class SampleDocTypeInfo(BaseModel):
    doc_type: str
    label: str
    folder: str
    count: int = 0


class SampleDocumentSummary(BaseModel):
    id: int
    doc_type: str
    doc_type_label: Optional[str] = None
    external_id: str
    title: str
    category: str
    source_url: Optional[str] = None
    has_file: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SampleDocumentDetail(SampleDocumentSummary):
    teaser: str = ""
    disclaimer: str = DISCLAIMER_FA


class SampleDocumentListResponse(BaseModel):
    total: int
    items: list[SampleDocumentSummary]
    disclaimer: str = DISCLAIMER_FA


class SampleDocumentTypesResponse(BaseModel):
    types: list[SampleDocTypeInfo]
    disclaimer: str = DISCLAIMER_FA


class SampleDocumentCategoriesResponse(BaseModel):
    doc_type: str
    categories: list[str]
