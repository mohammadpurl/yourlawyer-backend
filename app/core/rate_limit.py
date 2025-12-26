"""Rate limiting middleware using slowapi."""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request

from app.core.config import RATE_LIMIT_ENABLED, RATE_LIMIT_PER_MINUTE

limiter = Limiter(key_func=get_remote_address)


def get_rate_limit_string() -> str:
    """Get rate limit string for slowapi."""
    if RATE_LIMIT_ENABLED:
        return f"{RATE_LIMIT_PER_MINUTE}/minute"
    return "1000/minute"  # Very high limit if disabled


def setup_rate_limiting(app):
    """Setup rate limiting middleware."""
    if RATE_LIMIT_ENABLED:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    return app



