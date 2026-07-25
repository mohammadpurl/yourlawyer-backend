"""Persist citation grounding quality metrics."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.citation import CitationQualityLog
from app.services.citation_validator import CitationCheckResult


def persist_citation_quality_log(
    db: Session,
    *,
    result: CitationCheckResult,
    user_id: int | None = None,
    request_id: str | None = None,
) -> None:
    try:
        row = CitationQualityLog(
            request_id=request_id,
            user_id=user_id,
            cited_articles=list(result.cited_articles),
            unverified_citations=list(result.unverified_citations),
            confidence_flag=result.confidence_flag,
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        # Never break the user-facing ask path because of logging failure
        import logging

        logging.getLogger(__name__).exception("Failed to persist citation quality log")
