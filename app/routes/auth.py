from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, Base, engine
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
from app.services.otp import generate_otp, verify_otp, send_sms_mock
from app.models.user import User


router = APIRouter(prefix="/auth", tags=["auth"])


# Ensure tables exist (simple bootstrap)
Base.metadata.create_all(bind=engine)


# Register endpoint removed - registration happens via OTP verification


@router.post("/login")
def login_start(payload: SendOtpRequest):
    # Login is OTP-based: send code
    code = generate_otp(payload.phone)
    send_sms_mock(payload.phone, f"کد ورود شما: {code}")
    return {"sent": {code}}


@router.post("/otp/send")
def otp_send(payload: SendOtpRequest):
    code = generate_otp(payload.phone)
    # TODO: integrate real SMS provider; for now mock
    send_sms_mock(payload.phone, f"کد ورود شما: {code}")
    return {"sent": {code}}


@router.post("/otp/verify", response_model=TokenResponse)
def otp_verify(payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    ok = verify_otp(payload.phone, payload.code)
    if not ok:
        raise HTTPException(status_code=400, detail="کد وارد شده صحیح نیست")

    user = db.query(User).filter(User.phone == payload.phone).first()
    if not user:
        # Create minimal user with phone as username placeholder
        # Ensure unique username; fallback to phone-based username
        base_username = f"user_{payload.phone.strip('+')}"
        username = base_username
        suffix = 1
        while db.query(User).filter(User.username == username).first() is not None:
            suffix += 1
            username = f"{base_username}_{suffix}"
        user = create_user(db, username=username, phone=payload.phone)

    token = create_access_token(subject=str(user.username))
    return TokenResponse(access_token=token)


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
