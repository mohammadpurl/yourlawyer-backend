from uuid import uuid4
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, Base, engine
from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES
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
)
from app.services.otp import generate_otp, verify_otp, send_sms_mock, send_sms_real
from app.models.user import User


router = APIRouter(prefix="/auth", tags=["auth"])


# Ensure tables exist (simple bootstrap)
Base.metadata.create_all(bind=engine)


# Register endpoint removed - registration happens via OTP verification


@router.post("/login")
def login_start(payload: SendOtpRequest):
    # Login is OTP-based: send code
    code = generate_otp(payload.mobile)
    send_sms_real(payload.mobile, code)
    return {"sent": {code}}


@router.post("/otp/send")
def otp_send(payload: SendOtpRequest):
    code = generate_otp(payload.mobile)
    send_sms_real(payload.mobile, code)
    return {"sent": {code}}


@router.post("/otp/verify", response_model=TokenResponse)
def otp_verify(payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    ok = verify_otp(payload.mobile, payload.code)
    if not ok:
        raise HTTPException(status_code=400, detail="کد وارد شده صحیح نیست")

    user = db.query(User).filter(User.mobile == payload.mobile).first()
    if not user:
        # Create minimal user with mobile as username placeholder
        # Ensure unique username; fallback to mobile-based username
        base_username = f"user_{payload.mobile.strip('+')}"
        username = base_username
        suffix = 1
        while db.query(User).filter(User.username == username).first() is not None:
            suffix += 1
            username = f"{base_username}_{suffix}"
        user = create_user(db, username=username, mobile=payload.mobile)

    # Build session and token with aligned expiry
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    session_id = str(uuid4())

    access_token = create_access_token(
        subject=str(user.username),
        expires_delta=expire - now,
        session_id=session_id,
        user_name=user.username,
        full_name=user.username,  # تا وقتی فیلد جداگانه‌ای برای نام کامل نداریم
        pic="",  # می‌توانید بعداً از فیلد تصویر کاربر پرش کنید
    )

    return TokenResponse(
        accessToken=access_token,
        sessionId=session_id,
        sessionExpiry=int(expire.timestamp()),
    )


@router.put("/me")
def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Update allowed fields: username, email
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
