"""Public template endpoints — no LLM / no quota."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.templates import (
    TemplateCategoriesResponse,
    TemplateCategoryNode,
    TemplateDetail,
    TemplateFillRequest,
    TemplateSummary,
)
from app.services import templates as template_service

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/categories", response_model=TemplateCategoriesResponse)
def get_template_categories(db: Session = Depends(get_db)):
    nodes = [
        TemplateCategoryNode(**item) for item in template_service.list_categories(db)
    ]
    return TemplateCategoriesResponse(categories=nodes)


@router.get("", response_model=list[TemplateSummary])
def list_templates(
    category: str | None = Query(default=None),
    subcategory: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    rows = template_service.list_templates(
        db, category=category, subcategory=subcategory, active_only=True
    )
    return [TemplateSummary.model_validate(r) for r in rows]


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template_detail(template_id: int, db: Session = Depends(get_db)):
    row = template_service.get_template(db, template_id, active_only=True)
    return TemplateDetail.model_validate(row)


@router.get("/{template_id}/download-raw")
def download_raw_template(template_id: int, db: Session = Depends(get_db)):
    content, filename = template_service.raw_template_docx(db, template_id)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.post("/{template_id}/fill")
def fill_and_download_template(
    template_id: int,
    payload: TemplateFillRequest,
    db: Session = Depends(get_db),
):
    content, filename = template_service.fill_template_docx(
        db, template_id, payload.field_values
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
