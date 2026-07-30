from uuid import uuid4
from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db, Base, engine
from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.core.privacy import mask_mobile
from app.core.rate_limit import limiter
from app.schemas.auth import (
    TokenResponse,
    SendOtpRequest,
    VerifyOtpRequest,
    UpdateProfileRequest,
)
from app.services.auth import (
    create_user,
    create_access_token,
    get_current_user,
    sync_admin_flag,
)
from app.services.otp import generate_otp, verify_otp, send_sms_real
from app.models.user import User
from app.models.login_history import LoginHistory


router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# Ensure tables exist (simple bootstrap)
Base.metadata.create_all(bind=engine)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("X-Real-IP")
    if real:
        return real.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _record_login(
    db: Session,
    *,
    mobile: str,
    success: bool,
    user_id: int | None,
    ip: str | None,
) -> None:
    try:
        db.add(
            LoginHistory(
                user_id=user_id,
                mobile_masked=mask_mobile(mobile),
                ip=ip,
                success=success,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to record login history")


@router.post("/login")
@limiter.limit("5/minute")
def login_start(request: Request, payload: SendOtpRequest):
    code = generate_otp(payload.mobile)
    send_sms_real(payload.mobile, code)
    return {"sent": True}


@router.post("/otp/send")
@limiter.limit("5/minute")
def otp_send(request: Request, payload: SendOtpRequest):
    code = generate_otp(payload.mobile)
    send_sms_real(payload.mobile, code)
    logger.info("OTP sent to mobile ending %s", payload.mobile[-4:])
    return {"sent": True}


@router.post("/otp/verify", response_model=TokenResponse)
@limiter.limit("10/minute")
def otp_verify(
    request: Request,
    payload: VerifyOtpRequest,
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    ok = verify_otp(payload.mobile, payload.code)
    if not ok:
        _record_login(
            db, mobile=payload.mobile, success=False, user_id=None, ip=ip
        )
        raise HTTPException(status_code=400, detail="کد وارد شده صحیح نیست")

    user = db.query(User).filter(User.mobile == payload.mobile).first()
    if not user:
        base_username = f"user_{payload.mobile.strip('+')}"
        username = base_username
        suffix = 1
        while db.query(User).filter(User.username == username).first() is not None:
            suffix += 1
            username = f"{base_username}_{suffix}"
        user = create_user(db, username=username, mobile=payload.mobile)

    user = sync_admin_flag(user, db)
    _record_login(
        db, mobile=payload.mobile, success=True, user_id=user.id, ip=ip
    )

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    session_id = str(uuid4())

    access_token = create_access_token(
        subject=str(user.username),
        expires_delta=expire - now,
        session_id=session_id,
        user_name=user.username,
        full_name=user.username,
        pic="",
        is_admin=bool(user.is_admin),
    )

    return TokenResponse(
        accessToken=access_token,
        sessionId=session_id,
        sessionExpiry=int(expire.timestamp()),
        isAdmin=bool(user.is_admin),
    )


@router.put("/me")
def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.username:
        existing = (
            db.query(User)
            .filter(User.username == payload.username, User.id != current_user.id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400, detail="این نام کاربری قبلاً انتخاب شده است"
            )
        current_user.username = payload.username
    if payload.email is not None:
        if payload.email:
            existing_email = (
                db.query(User)
                .filter(User.email == payload.email, User.id != current_user.id)
                .first()
            )
            if existing_email:
                raise HTTPException(
                    status_code=400, detail="این ایمیل قبلاً استفاده شده است"
                )
        current_user.email = payload.email
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {"updated": True}
