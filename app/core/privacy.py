"""Mobile / PII masking helpers for admin and public APIs."""

from __future__ import annotations


def mask_mobile(mobile: str | None) -> str:
    """
    Mask Iranian-style mobiles for display, e.g. ``0912***0811``.

    Always masks — even for admin responses in v1.
    """
    if not mobile:
        return "***"
    digits = "".join(ch for ch in mobile.strip() if ch.isdigit())
    if len(digits) < 7:
        return "***"
    return f"{digits[:4]}***{digits[-4:]}"
