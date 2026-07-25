"""FastAPI dependency: block requests when monthly USD quota is exhausted."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.quota import check_quota_available


def check_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """
    Run before any endpoint that may call OpenAI (classify / rerank / generate).
    Returns the authenticated user for convenience.
    """
    check_quota_available(db, current_user)
    return current_user
