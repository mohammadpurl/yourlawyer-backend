import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes.auth import router as auth_router
from app.routes.rag import router as rag_router
from app.routes.conversation import router as conversation_router
from app.routes.plan import router as plan_router
from app.core.database import Base, engine
from app.core.logging import configure_logging
from app.core.monitoring import init_sentry
from app.core.config import (
    ALLOWED_ORIGINS,
    IP_WHITELIST_ENABLED,
    ALLOWED_IPS,
    IP_WHITELIST_EXEMPT_PATHS,
    DOCS_ENABLED,
)
from app.core.rate_limit import setup_rate_limiting

# Import models to ensure they are registered in metadata
import app.models.user  # noqa: F401


configure_logging()
init_sentry()

logger = logging.getLogger("app.main")

# Get root_path from environment variable for reverse proxy support
# This is needed when FastAPI is behind a reverse proxy (e.g., nginx) with a subpath
ROOT_PATH = os.getenv("ROOT_PATH", "").strip()
# اگر ROOT_PATH تنظیم نشده، سعی می‌کنیم از /backend استفاده کنیم (برای سازگاری)
if not ROOT_PATH:
    ROOT_PATH = "/backend"
root_path_value = ROOT_PATH if ROOT_PATH else None


def _configure_openapi(application: FastAPI) -> None:
    """Configure OpenAPI schema with Bearer auth and root_path servers."""
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema

        openapi_schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )

        openapi_schema["components"]["securitySchemes"] = {
            "Bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "توکن را از endpoint `/auth/otp/verify` دریافت کنید. ابتدا با شماره موبایل و OTP لاگین کنید، سپس `accessToken` را در اینجا وارد کنید.",
            }
        }

        server_url = root_path_value
        if not server_url and hasattr(application.state, "detected_root_path"):
            server_url = application.state.detected_root_path
        if not server_url:
            server_url = "/backend"

        openapi_schema["servers"] = [
            {
                "url": server_url,
                "description": "Production server with root path",
            }
        ]

        application.openapi_schema = openapi_schema
        return application.openapi_schema

    application.openapi = custom_openapi


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifespan: create DB tables and configure OpenAPI on startup."""
    Base.metadata.create_all(bind=engine)
    _configure_openapi(application)
    logger.info("Startup completed: database tables ensured")
    yield


app = FastAPI(
    title="YourLawyer RAG (IR)",
    description="API برای سیستم دستیار حقوقی با RAG و پشتیبانی از گفتگوها",
    version="1.0.0",
    root_path=root_path_value,
    root_path_in_servers=True,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
    lifespan=lifespan,
)


def get_client_ip(request: Request) -> str:
    """
    استخراج IP واقعی کلاینت از header های مختلف.
    این برای زمانی است که سرور پشت reverse proxy (nginx, load balancer) باشد.
    """
    # اولویت: X-Forwarded-For (ممکن است چند IP باشد، اولی را می‌گیریم)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For می‌تواند چند IP داشته باشد (مثلاً: "client, proxy1, proxy2")
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    # دوم: X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # سوم: مستقیماً از client
    if request.client:
        return request.client.host

    return "unknown"


def ip_in_subnet(ip: str, subnet: str) -> bool:
    """
    بررسی اینکه آیا IP در subnet قرار دارد یا نه.

    Args:
        ip: IP آدرس (مثلاً "172.18.0.1")
        subnet: subnet با CIDR notation (مثلاً "172.18.0.0/16")

    Returns:
        True اگر IP در subnet باشد
    """
    try:
        import ipaddress

        # اگر subnet نیست (فقط IP است)، مقایسه مستقیم
        if "/" not in subnet:
            return ip == subnet

        # بررسی subnet
        network = ipaddress.ip_network(subnet, strict=False)
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj in network
    except (ValueError, AttributeError):
        # در صورت خطا، مقایسه مستقیم
        return ip == subnet


def is_ip_allowed(client_ip: str, allowed_ips: list) -> bool:
    """
    بررسی اینکه آیا IP کلاینت در لیست مجاز است یا نه.
    این تابع هم IP های دقیق و هم subnet ها را پشتیبانی می‌کند.

    Args:
        client_ip: IP کلاینت
        allowed_ips: لیست IP ها و subnet های مجاز

    Returns:
        True اگر IP مجاز باشد
    """
    # بررسی IP های دقیق و subnet ها
    for allowed_ip in allowed_ips:
        if ip_in_subnet(client_ip, allowed_ip):
            return True

    # بررسی localhost و 127.x.x.x
    if (
        client_ip == "127.0.0.1"
        or client_ip.startswith("127.")
        or client_ip == "localhost"
        or client_ip == "::1"  # IPv6 localhost
    ):
        return True

    return False


@app.middleware("http")
async def ip_whitelist_middleware(request: Request, call_next):
    """
    Middleware برای محدود کردن دسترسی به IP های مجاز.
    این middleware درخواست‌ها را بررسی می‌کند و فقط از IP های مجاز اجازه دسترسی می‌دهد.
    """
    # اگر IP whitelist غیرفعال باشد، همه درخواست‌ها را اجازه می‌دهیم
    if not IP_WHITELIST_ENABLED:
        response = await call_next(request)
        return response

    # بررسی مسیرهای مستثنی
    path = request.url.path
    # حذف root_path از مسیر برای بررسی
    if root_path_value and path.startswith(root_path_value):
        path = path[len(root_path_value) :] or "/"

    # بررسی اینکه آیا مسیر در لیست مستثنی‌ها است
    is_exempt = any(
        path == exempt_path or path.startswith(exempt_path + "/")
        for exempt_path in IP_WHITELIST_EXEMPT_PATHS
    )

    if is_exempt:
        # مسیرهای مستثنی (مثل /health) را بدون بررسی IP اجازه می‌دهیم
        response = await call_next(request)
        return response

    # استخراج IP کلاینت
    client_ip = get_client_ip(request)

    # بررسی اینکه IP در لیست مجاز است یا نه (با پشتیبانی از subnet)
    allowed = is_ip_allowed(client_ip, ALLOWED_IPS)

    if not allowed:
        security_logger = logging.getLogger("app.security")
        security_logger.warning(
            f"IP whitelist violation | IP={client_ip} | Path={request.url.path} | Method={request.method}",
            extra={
                "client_ip": client_ip,
                "path": request.url.path,
                "method": request.method,
                "headers": dict(request.headers),
            },
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": "دسترسی غیرمجاز: IP شما در لیست مجاز نیست",
                "error_code": "IP_NOT_ALLOWED",
            },
        )

    response = await call_next(request)
    return response


@app.middleware("http")
async def detect_root_path(request: Request, call_next):
    """
    Middleware برای تشخیص خودکار root_path از URL درخواست.
    این برای زمانی است که ROOT_PATH در environment variable تنظیم نشده باشد.
    """
    # اگر root_path_value تنظیم نشده باشد، سعی می‌کنیم از URL تشخیص دهیم
    if not root_path_value and request.url.path.startswith("/backend"):
        # تشخیص root_path از URL
        detected_root = "/backend"
        # ذخیره در app state برای استفاده در custom_openapi
        if not hasattr(app.state, "detected_root_path"):
            app.state.detected_root_path = detected_root
            # به‌روزرسانی openapi_schema اگر قبلاً ساخته شده باشد
            if hasattr(app, "openapi_schema") and app.openapi_schema:
                app.openapi_schema = None  # Force regeneration

    response = await call_next(request)
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware برای لاگ‌کردن همه درخواست‌ها و پاسخ‌ها.
    """
    request_logger = logging.getLogger("app.request")
    # استخراج IP کلاینت برای لاگ
    client_ip = get_client_ip(request)
    # هدر Authorization را برای دیباگ ثبت می‌کنیم (توکن را ماسک می‌کنیم)
    auth_header = request.headers.get("authorization")
    masked_auth = None
    if auth_header:
        # فقط چند کاراکتر اول و آخر را نشان می‌دهیم
        masked_auth = (
            f"{auth_header[:15]}...{auth_header[-5:]}"
            if len(auth_header) > 25
            else auth_header
        )

    request_logger.info(
        f"REQUEST {request.method} {request.url.path} | IP={client_ip}",
        extra={
            "authorization_present": bool(auth_header),
            "authorization": masked_auth,
            "client_ip": client_ip,
        },
    )
    try:
        response = await call_next(request)
        request_logger.info(
            f"RESPONSE {request.method} {request.url.path} -> {response.status_code} | IP={client_ip}",
            extra={
                "client_ip": client_ip,
            },
        )
        return response
    except Exception:
        # هر خطای کنترل‌نشده را لاگ می‌کنیم و دوباره raise می‌کنیم
        request_logger.exception(
            f"UNHANDLED ERROR for {request.method} {request.url.path}"
        )
        raise


# Setup rate limiting
app = setup_rate_limiting(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "ok", "service": "yourlawyer-rag-api"}


if DOCS_ENABLED:

    @app.get("/openapi.json", include_in_schema=False)
    async def get_openapi_json():
        """Endpoint برای بازگرداندن OpenAPI schema با در نظر گیری root_path."""
        return app.openapi()

    @app.get("/backend/openapi.json", include_in_schema=False)
    async def get_openapi_json_backend():
        """Endpoint برای بازگرداندن OpenAPI schema از مسیر /backend/openapi.json."""
        return app.openapi()


app.include_router(auth_router)
app.include_router(rag_router)
app.include_router(conversation_router)
app.include_router(plan_router)


@app.exception_handler(HTTPException)
async def http_exception_logger(request: Request, exc: HTTPException):
    """
    لاگر مرکزی برای همه HTTPException ها.
    """
    error_logger = logging.getLogger("app.errors")
    error_logger.error(
        "HTTPException | status=%s | path=%s | detail=%s",
        exc.status_code,
        request.url.path,
        exc.detail,
        exc_info=True,
    )
    # همان detail را به فرانت برمی‌گردانیم
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_logger(request: Request, exc: Exception):
    """
    لاگر مرکزی برای همه خطاهای غیرمنتظره (500).
    """
    error_logger = logging.getLogger("app.errors")
    error_logger.error(
        "Unhandled exception | path=%s | error=%s",
        request.url.path,
        exc,
        exc_info=True,
    )
    # پیام کلی به فرانت، جزئیات کامل در لاگ
    return JSONResponse(
        status_code=500,
        content={"detail": "خطای داخلی سرور رخ داد. لطفاً بعداً دوباره تلاش کنید."},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
