from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session
import logging

from app.core.database import get_db
from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.models.user import User, PlanType
from datetime import date


# استفاده از HTTPBearer برای پشتیبانی از Bearer Token در Swagger
# scheme_name باید با securitySchemes در openapi (Bearer) یکی باشد.
security = HTTPBearer(scheme_name="Bearer")


def get_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """استخراج توکن از header Authorization"""
    logger = logging.getLogger("app.auth")
    token_preview = (
        credentials.credentials[:10] + "..."
        if credentials and credentials.credentials
        else None
    )
    logger.info(
        "Authorization header received",
        extra={
            "scheme": credentials.scheme if credentials else None,
            "token_preview": token_preview,
        },
    )
    return credentials.credentials


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
    session_id: Optional[str] = None,
    user_name: Optional[str] = None,
    full_name: Optional[str] = None,
    pic: Optional[str] = None,
    is_admin: bool = False,
) -> str:
    """
    Create an access JWT.

    The payload is aligned with the frontend `JWT` interface:
      export interface JWT {
          userName: string;
          fullName: string;
          pic: string;
          exp: number;
          isAdmin?: boolean;
      }
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode: dict[str, object] = {
        "sub": subject,
        "exp": int(expire.timestamp()),
        "type": "access",
        "userName": user_name or subject,
        "fullName": full_name or subject,
        "pic": pic or "",
        "isAdmin": bool(is_admin),
    }
    if session_id is not None:
        to_encode["sid"] = session_id
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def create_user(
    db: Session,
    username: str,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
) -> User:
    # تنظیم پلن پیش‌فرض (رایگان) و تاریخ ریست
    today = date.today()
    if today.month == 12:
        reset_date = date(today.year + 1, 1, 1)
    else:
        reset_date = date(today.year, today.month + 1, 1)

    user = User(
        username=username,
        email=email,
        mobile=mobile,
        plan_type=PlanType.FREE,
        questions_used=0,
        plan_reset_date=reset_date,
        is_admin=_mobile_in_admin_allowlist(mobile),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _normalize_mobile(mobile: str | None) -> str:
    if not mobile:
        return ""
    return "".join(ch for ch in mobile.strip() if ch.isdigit() or ch == "+")


def _mobile_in_admin_allowlist(mobile: str | None) -> bool:
    from app.core.config import ADMIN_MOBILES

    if not mobile or not ADMIN_MOBILES:
        return False
    normalized = _normalize_mobile(mobile)
    allow = {_normalize_mobile(m) for m in ADMIN_MOBILES}
    # Also compare last 10 digits (09xxxxxxxxx) for +98 variants
    def tail10(value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits[-10:] if len(digits) >= 10 else digits

    return normalized in allow or tail10(normalized) in {tail10(a) for a in allow}


def sync_admin_flag(user: User, db: Session) -> User:
    """Keep user.is_admin aligned with ADMIN_MOBILES allowlist."""
    should_be_admin = _mobile_in_admin_allowlist(user.mobile)
    if bool(user.is_admin) != should_be_admin:
        user.is_admin = should_be_admin
        db.commit()
        db.refresh(user)
    return user


def get_current_user(
    token: str = Depends(get_token), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=401, detail="Could not validate credentials"
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_error
    except JWTError:
        raise credentials_error
    user = get_user_by_username(db, username)
    if user is None:
        raise credentials_error
    return sync_admin_flag(user, db)
