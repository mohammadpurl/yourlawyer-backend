"""Pydantic schemas for document templates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.template import TemplateCategory


class TemplateFieldDef(BaseModel):
    key: str
    label: str
    type: str = "string"  # string | number | date
    required: bool = True


class TemplateFieldSchema(BaseModel):
    fields: list[TemplateFieldDef] = Field(default_factory=list)


class TemplateSummary(BaseModel):
    id: int
    category: str
    subcategory: str
    title: str
    description: Optional[str] = None
    source_reference: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class TemplateDetail(TemplateSummary):
    body_template: str
    field_schema: dict[str, Any]
    created_at: Optional[datetime] = None


class TemplateFillRequest(BaseModel):
    field_values: dict[str, Any] = Field(default_factory=dict)


class TemplateCreateRequest(BaseModel):
    category: TemplateCategory
    subcategory: str
    title: str
    description: Optional[str] = None
    body_template: str
    field_schema: dict[str, Any]
    source_reference: Optional[str] = None
    is_active: bool = True


class TemplateUpdateRequest(BaseModel):
    category: Optional[TemplateCategory] = None
    subcategory: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    body_template: Optional[str] = None
    field_schema: Optional[dict[str, Any]] = None
    source_reference: Optional[str] = None
    is_active: Optional[bool] = None


class TemplateCategoryNode(BaseModel):
    category: str
    category_label: str
    subcategories: list[str]


class TemplateCategoriesResponse(BaseModel):
    categories: list[TemplateCategoryNode]
