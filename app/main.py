import logging
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes.auth import router as auth_router
from app.routes.rag import router as rag_router
from app.routes.conversation import router as conversation_router
from app.core.database import Base, engine
from app.core.logging import configure_logging
from app.core.monitoring import init_sentry
from app.core.config import ALLOWED_ORIGINS
from app.core.rate_limit import setup_rate_limiting

# Import models to ensure they are registered in metadata
import app.models.user  # noqa: F401


configure_logging()
init_sentry()

logger = logging.getLogger("app.main")

# Get root_path from environment variable for reverse proxy support
# This is needed when FastAPI is behind a reverse proxy (e.g., nginx) with a subpath
ROOT_PATH = os.getenv("ROOT_PATH", "").strip()
root_path_value = ROOT_PATH if ROOT_PATH else None

app = FastAPI(
    title="YourLawyer RAG (IR)",
    description="API برای سیستم دستیار حقوقی با RAG و پشتیبانی از گفتگوها",
    version="1.0.0",
    root_path=root_path_value,
    root_path_in_servers=True,  # اضافه کردن root_path به servers در OpenAPI schema
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware برای لاگ‌کردن همه درخواست‌ها و پاسخ‌ها.
    """
    request_logger = logging.getLogger("app.request")
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
        f"REQUEST {request.method} {request.url.path}",
        extra={
            "authorization_present": bool(auth_header),
            "authorization": masked_auth,
        },
    )
    try:
        response = await call_next(request)
        request_logger.info(
            f"RESPONSE {request.method} {request.url.path} -> {response.status_code}"
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


app.include_router(auth_router)
app.include_router(rag_router)
app.include_router(conversation_router)


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


@app.on_event("startup")
def on_startup() -> None:
    """تنظیمات اولیه هنگام راه‌اندازی سرور"""
    # Create all tables if they do not exist
    Base.metadata.create_all(bind=engine)
    logger.info("Startup completed: database tables ensured")

    # تنظیم Swagger UI برای پشتیبانی از Bearer Token و root_path
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        # اضافه کردن Security Scheme برای Bearer Token
        openapi_schema["components"]["securitySchemes"] = {
            "Bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "توکن را از endpoint `/auth/otp/verify` دریافت کنید. ابتدا با شماره موبایل و OTP لاگین کنید، سپس `accessToken` را در اینجا وارد کنید.",
            }
        }

        # اضافه کردن servers برای پشتیبانی از root_path
        if root_path_value:
            # اگر root_path تنظیم شده، آن را به servers اضافه می‌کنیم
            openapi_schema["servers"] = [
                {
                    "url": root_path_value,
                    "description": "Production server with root path",
                }
            ]
        else:
            # اگر root_path تنظیم نشده، از root استفاده می‌کنیم
            openapi_schema["servers"] = [
                {
                    "url": "/",
                    "description": "Default server",
                }
            ]

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
