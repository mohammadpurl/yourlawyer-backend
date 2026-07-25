"""Tests for admin.manage permission (no shared secret header)."""

from app.core.permissions import Permission, user_has_permission
from app.services.auth import _mobile_in_admin_allowlist


class _FakeUser:
    def __init__(self, is_admin: bool):
        self.is_admin = is_admin


def test_admin_manage_requires_is_admin():
    assert user_has_permission(_FakeUser(True), Permission.ADMIN_MANAGE)
    assert not user_has_permission(_FakeUser(False), Permission.ADMIN_MANAGE)


def test_admin_mobile_allowlist(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.ADMIN_MOBILES",
        ["09121234567", "+989121111111"],
    )
    assert _mobile_in_admin_allowlist("09121234567")
    assert _mobile_in_admin_allowlist("+989121111111")
    assert _mobile_in_admin_allowlist("989121111111")
    assert not _mobile_in_admin_allowlist("09120000000")
