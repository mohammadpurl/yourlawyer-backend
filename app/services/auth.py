from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
    session_id: Optional[str] = None,
    user_name: Optional[str] = None,
    full_name: Optional[str] = None,
    pic: Optional[str] = None,
) -> str:
    """
    Create an access JWT.

    The payload is aligned with the frontend `JWT` interface:
      export interface JWT {
          userName: string;
          fullName: string;
          pic: string;
          exp: number;
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
    user = User(username=username, email=email, mobile=mobile)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
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
    return user
