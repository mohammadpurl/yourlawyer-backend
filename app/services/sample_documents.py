"""Sample document catalog service (Solh library) — no LLM / no Chroma."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import BASE_DIR
from app.core.security_utils import validate_path
from app.models.sample_document import SampleDocument, SampleDocType

DATA_ROOT = (BASE_DIR / "data").resolve()

DOC_TYPE_META: list[dict[str, str]] = [
    {
        "doc_type": SampleDocType.CONTRACT.value,
        "label": "قراردادها",
        "folder": "outputs_solh_contracts",
    },
    {
        "doc_type": SampleDocType.PETITION.value,
        "label": "دادخواست‌ها",
        "folder": "outputs_solh_petition",
    },
    {
        "doc_type": SampleDocType.POWER_OF_ATTORNEY.value,
        "label": "وکالت‌نامه‌ها",
        "folder": "outputs_solh_power_of_attorney",
    },
    {
        "doc_type": SampleDocType.COMPLAINT.value,
        "label": "شکواییه / شکایت",
        "folder": "outputs_solh_complaint",
    },
    {
        "doc_type": SampleDocType.CONFIRMATION.value,
        "label": "اقرارنامه",
        "folder": "outputs_solh_confirmation",
    },
    {
        "doc_type": SampleDocType.DECLARATION.value,
        "label": "اظهارنامه",
        "folder": "outputs_solh_declaration",
    },
    {
        "doc_type": SampleDocType.COMPANY_STATUTE.value,
        "label": "اساسنامه / ثبت شرکت",
        "folder": "outputs_solh_company_statute",
    },
]

_WS_RE = re.compile(r"[\s\u200c\u200f\u202a-\u202e]+")


def normalize_fa(text: str) -> str:
    """Normalize Persian/Arabic letters and whitespace for search."""
    if not text:
        return ""
    s = text.strip()
    s = s.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    s = s.replace("ۀ", "ه").replace("ة", "ه").replace("ؤ", "و").replace("أ", "ا").replace("إ", "ا")
    s = _WS_RE.sub(" ", s)
    return s.strip()


def tokenize_query(q: str) -> list[str]:
    """Split search query into meaningful tokens (AND semantics)."""
    norm = normalize_fa(q)
    if not norm:
        return []
    tokens = [t for t in norm.split(" ") if t]
    # Drop ultra-short noise unless the whole query is one short token
    if len(tokens) == 1:
        return tokens
    return [t for t in tokens if len(t) >= 2]


def _fa_norm_sql(col: ColumnElement) -> ColumnElement:
    """SQL-side Persian letter normalization for ILIKE matching."""
    expr = func.replace(func.replace(col, "ي", "ی"), "ى", "ی")
    expr = func.replace(expr, "ك", "ک")
    return expr


def list_doc_types(db: Session | None = None) -> list[dict]:
    meta = [dict(t) for t in DOC_TYPE_META]
    if db is None:
        for t in meta:
            t["count"] = 0
        return meta

    counts = dict(
        db.query(SampleDocument.doc_type, func.count(SampleDocument.id))
        .filter(SampleDocument.is_active.is_(True))
        .group_by(SampleDocument.doc_type)
        .all()
    )
    for t in meta:
        t["count"] = int(counts.get(t["doc_type"], 0))
    return meta


def resolve_sample_file(file_path: str) -> Path:
    """Resolve DB-relative path under data/ and block path traversal."""
    rel = file_path.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise HTTPException(status_code=400, detail="مسیر فایل نامعتبر است")
    candidate = (DATA_ROOT / rel).resolve()
    ok, safe = validate_path(candidate, base_dirs=[DATA_ROOT])
    if not ok:
        raise HTTPException(status_code=400, detail="مسیر فایل خارج از محدوده مجاز است")
    if not safe.is_file():
        raise HTTPException(status_code=404, detail="فایل نمونه یافت نشد")
    if safe.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="فقط فایل PDF قابل دانلود است")
    return safe


def get_sample(db: Session, sample_id: int) -> SampleDocument:
    row = (
        db.query(SampleDocument)
        .filter(SampleDocument.id == sample_id, SampleDocument.is_active.is_(True))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="نمونه سند یافت نشد")
    return row


def list_samples(
    db: Session,
    *,
    doc_type: str | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SampleDocument], int]:
    query = db.query(SampleDocument).filter(SampleDocument.is_active.is_(True))
    if doc_type:
        query = query.filter(SampleDocument.doc_type == doc_type)
    if category:
        query = query.filter(SampleDocument.category == category)

    tokens = tokenize_query(q or "")
    title_n = _fa_norm_sql(SampleDocument.title)
    category_n = _fa_norm_sql(SampleDocument.category)

    if tokens:
        for token in tokens:
            like = f"%{token}%"
            query = query.filter(or_(title_n.ilike(like), category_n.ilike(like)))

        # Rank: exact / prefix / contains in title, else category-only match
        full = " ".join(tokens)
        whens: list[tuple] = [
            (title_n.ilike(full), 100),
            (title_n.ilike(f"{full}%"), 90),
            (title_n.ilike(f"%{full}%"), 70),
        ]
        for i, t in enumerate(tokens[:5]):
            whens.append((title_n.ilike(f"%{t}%"), 50 - i))
        rank = case(*whens, else_=10)
        order = (rank.desc(), SampleDocument.title.asc(), SampleDocument.id.asc())
    else:
        order = (
            SampleDocument.doc_type.asc(),
            SampleDocument.category.asc(),
            SampleDocument.title.asc(),
            SampleDocument.id.asc(),
        )

    total = query.count()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = query.order_by(*order).offset(offset).limit(limit).all()
    return rows, total


def list_categories(db: Session, doc_type: str | None = None) -> list[str]:
    q = db.query(SampleDocument.category).filter(SampleDocument.is_active.is_(True))
    if doc_type:
        q = q.filter(SampleDocument.doc_type == doc_type)
    rows = q.distinct().order_by(SampleDocument.category).all()
    return [r[0] for r in rows if r[0]]
