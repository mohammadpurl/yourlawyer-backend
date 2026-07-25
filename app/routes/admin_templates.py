"""Admin CRUD for document templates (admin.manage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_admin_manage
from app.models.user import User
from app.schemas.templates import (
    TemplateCreateRequest,
    TemplateDetail,
    TemplateSummary,
    TemplateUpdateRequest,
)
from app.services import templates as template_service

router = APIRouter(prefix="/admin/templates", tags=["admin-templates"])


@router.get("", response_model=list[TemplateSummary])
def admin_list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    rows = template_service.list_templates(db, active_only=False)
    return [TemplateSummary.model_validate(r) for r in rows]


@router.post("", response_model=TemplateDetail)
def admin_create_template(
    payload: TemplateCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    data = payload.model_dump()
    data["category"] = payload.category.value
    row = template_service.create_template(db, data)
    return TemplateDetail.model_validate(row)


@router.put("/{template_id}", response_model=TemplateDetail)
def admin_update_template(
    template_id: int,
    payload: TemplateUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_manage),
):
    data = payload.model_dump(exclude_unset=True)
    if "category" in data and data["category"] is not None:
        data["category"] = (
            data["category"].value
            if hasattr(data["category"], "value")
            else data["category"]
        )
    row = template_service.update_template(db, template_id, data)
    return TemplateDetail.model_validate(row)
