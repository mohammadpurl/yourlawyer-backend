"""Optional observability hooks (Sentry, tracing)."""

from __future__ import annotations

import os
from typing import Optional

SENTRY_DSN = os.getenv("SENTRY_DSN")


def init_sentry() -> Optional[object]:
    """Initialise Sentry SDK if configuration is provided."""

    if not SENTRY_DSN:
        return None

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError as exc:  # pragma: no cover - runtime safeguard
        raise RuntimeError(
            "Sentry integration requested but 'sentry-sdk' is not installed"
        ) from exc

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.getenv("SENTRY_ENV", "development"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        profiles_sample_rate=float(
            os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.0")
        ),
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        send_default_pii=os.getenv("SENTRY_SEND_PII", "false").lower() == "true",
    )

    return sentry_sdk

