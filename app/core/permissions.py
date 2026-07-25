"""Application permissions (RBAC-lite).

Admin capabilities use JWT-authenticated users with ``is_admin`` / permission
``admin.manage``. Do not introduce parallel shared secrets for admin actions.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException

from app.models.user import User
from app.services.auth import get_current_user


class Permission(str, Enum):
    ADMIN_MANAGE = "admin.manage"


def user_has_permission(user: User, permission: Permission | str) -> bool:
    perm = permission.value if isinstance(permission, Permission) else permission
    if perm == Permission.ADMIN_MANAGE.value:
        return bool(getattr(user, "is_admin", False))
    return False


def require_permission(permission: Permission) -> Callable:
    """FastAPI dependency factory: require an authenticated user with permission."""

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if not user_has_permission(current_user, permission):
            raise HTTPException(
                status_code=403,
                detail=f"مجوز لازم نیست: {permission.value}",
            )
        return current_user

    return _dependency


require_admin_manage = require_permission(Permission.ADMIN_MANAGE)
