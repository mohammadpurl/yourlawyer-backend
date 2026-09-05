"""Solh sample-document library API — public catalog; download open for now (rate-limit later)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.sample_documents import (
    DISCLAIMER_FA,
    SampleDocumentCategoriesResponse,
    SampleDocumentDetail,
    SampleDocumentListResponse,
    SampleDocumentSummary,
    SampleDocumentTypesResponse,
    SampleDocTypeInfo,
)
from app.services import sample_documents as sample_service

router = APIRouter(prefix="/sample-documents", tags=["sample-documents"])


def _label_for(doc_type: str) -> str:
    for t in sample_service.DOC_TYPE_META:
        if t["doc_type"] == doc_type:
            return t["label"]
    return doc_type


def _summary(row) -> SampleDocumentSummary:
    return SampleDocumentSummary(
        id=row.id,
        doc_type=row.doc_type,
        doc_type_label=_label_for(row.doc_type),
        external_id=row.external_id,
        title=row.title,
        category=row.category,
        source_url=row.source_url,
        has_file=True,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


@router.get("/types", response_model=SampleDocumentTypesResponse)
def get_types(db: Session = Depends(get_db)):
    types = [SampleDocTypeInfo(**t) for t in sample_service.list_doc_types(db)]
    return SampleDocumentTypesResponse(types=types, disclaimer=DISCLAIMER_FA)


@router.get("/categories", response_model=SampleDocumentCategoriesResponse)
def get_categories(
    doc_type: str | None = Query(default=None, description="e.g. contract; omit for all"),
    db: Session = Depends(get_db),
):
    cats = sample_service.list_categories(db, doc_type)
    return SampleDocumentCategoriesResponse(doc_type=doc_type or "", categories=cats)


@router.get("", response_model=SampleDocumentListResponse)
def list_sample_documents(
    doc_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Search in title/category"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows, total = sample_service.list_samples(
        db,
        doc_type=doc_type,
        category=category,
        q=q,
        limit=limit,
        offset=offset,
    )
    return SampleDocumentListResponse(
        total=total,
        items=[_summary(r) for r in rows],
        disclaimer=DISCLAIMER_FA,
    )


@router.get("/{sample_id}", response_model=SampleDocumentDetail)
def get_sample_document(sample_id: int, db: Session = Depends(get_db)):
    row = sample_service.get_sample(db, sample_id)
    label = _label_for(row.doc_type)
    teaser = (
        f"نمونه {label}"
        + (f" در دسته «{row.category}»" if row.category else "")
        + f": {row.title}. "
        "متن کامل و فایل PDF پس از مشاهده در دسترس است."
    )
    return SampleDocumentDetail(
        id=row.id,
        doc_type=row.doc_type,
        doc_type_label=label,
        external_id=row.external_id,
        title=row.title,
        category=row.category,
        source_url=row.source_url,
        has_file=True,
        teaser=teaser,
        disclaimer=DISCLAIMER_FA,
        seo_title=getattr(row, "seo_title", None),
        seo_description=getattr(row, "seo_description", None),
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


@router.get("/{sample_id}/download")
def download_sample_document(sample_id: int, db: Session = Depends(get_db)):
    """Public download for now; rate limiting will be added later."""
    row = sample_service.get_sample(db, sample_id)
    path = sample_service.resolve_sample_file(row.file_path)
    filename = path.name
    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=filename,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
