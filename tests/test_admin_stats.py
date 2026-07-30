"""Tests for admin stats + mobile masking."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.privacy import mask_mobile
from app.core.permissions import Permission, user_has_permission


def test_mask_mobile_iranian():
    assert mask_mobile("091212340811") == "0912***0811"
    assert mask_mobile("+9891212340811") == "9891***0811"
    assert mask_mobile(None) == "***"
    assert mask_mobile("0912") == "***"


def test_mask_mobile_preserves_length_pattern():
    assert mask_mobile("09123456789") == "0912***6789"


def test_admin_permission_requires_is_admin():
    admin = SimpleNamespace(is_admin=True)
    user = SimpleNamespace(is_admin=False)
    assert user_has_permission(admin, Permission.ADMIN_MANAGE) is True
    assert user_has_permission(user, Permission.ADMIN_MANAGE) is False
