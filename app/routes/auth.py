from uuid import uuid4
from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db, Base, engine
from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, AVATAR_DIRECTORY
from app.core.privacy import mask_mobile
from app.core.rate_limit import limiter
from app.schemas.auth import (
    TokenResponse,
    SendOtpRequest,
    VerifyOtpRequest,
    UpdateProfileRequest,
    ProfileResponse,
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


_AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _profile_payload(user: User) -> ProfileResponse:
    has_avatar = bool(user.avatar_path)
    plan = user.plan_type.value if hasattr(user.plan_type, "value") else str(user.plan_type)
    return ProfileResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        mobile=user.mobile,
        mobile_masked=mask_mobile(user.mobile),
        plan_type=plan,
        is_admin=bool(user.is_admin),
        has_avatar=has_avatar,
        avatar_url="/auth/me/avatar" if has_avatar else None,
    )


def _resolve_avatar_file(user: User):
    if not user.avatar_path:
        return None
    path = AVATAR_DIRECTORY / user.avatar_path
    if not path.is_file():
        return None
    return path


@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return _profile_payload(current_user)


@router.get("/me/avatar")
def get_my_avatar(current_user: User = Depends(get_current_user)):
    path = _resolve_avatar_file(current_user)
    if not path:
        raise HTTPException(status_code=404, detail="تصویر پروفایل یافت نشد")
    media = "image/jpeg"
    suffix = path.suffix.lower()
    if suffix == ".png":
        media = "image/png"
    elif suffix == ".webp":
        media = "image/webp"
    return FileResponse(path, media_type=media)


@router.post("/me/avatar", response_model=ProfileResponse)
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content_type = (file.content_type or "").lower()
    if content_type not in _AVATAR_TYPES:
        raise HTTPException(
            status_code=400,
            detail="فقط تصویرهای JPG، PNG یا WebP مجاز است",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="فایل خالی است")
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=400, detail="حجم تصویر نباید بیشتر از ۲ مگابایت باشد"
        )

    AVATAR_DIRECTORY.mkdir(parents=True, exist_ok=True)

    # Remove previous avatar files for this user
    for old in AVATAR_DIRECTORY.glob(f"{current_user.id}.*"):
        try:
            old.unlink()
        except OSError:
            logger.warning("Could not remove old avatar %s", old)

    ext = _AVATAR_TYPES[content_type]
    filename = f"{current_user.id}{ext}"
    dest = AVATAR_DIRECTORY / filename
    dest.write_bytes(data)

    current_user.avatar_path = filename
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _profile_payload(current_user)
