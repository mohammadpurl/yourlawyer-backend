"""User payment history API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.payment import Payment
from app.models.user import User
from app.schemas.payment import PaymentItem, PaymentListResponse
from app.services.auth import get_current_user

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/mine", response_model=PaymentListResponse)
def list_my_payments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Payment)
        .filter(Payment.user_id == current_user.id)
        .order_by(Payment.created_at.desc())
        .limit(100)
        .all()
    )
    items = [PaymentItem.model_validate(r) for r in rows]
    return PaymentListResponse(items=items, total=len(items))
