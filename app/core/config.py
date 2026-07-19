import os
from pathlib import Path
from typing import List

# Hugging Face Hub settings must be set before huggingface_hub is imported anywhere.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _ensure_dir(path: Path) -> None:
    """Create directory when possible; do not crash on read-only/root-owned mounts."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


# Storage directories
PERSIST_DIRECTORY = Path(
    os.getenv("CHROMA_DB_DIR", BASE_DIR / "storage" / "chroma")
).as_posix()
UPLOAD_DIRECTORY = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
_ensure_dir(UPLOAD_DIRECTORY)

# Database
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'storage' / 'app.db').as_posix()}"
)

# Embeddings
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
LOCAL_EMBEDDING_MODEL_DIR = BASE_DIR / "storage" / "models" / "multilingual-e5-base"
_env_model = os.getenv("EMBEDDING_MODEL")
if _env_model:
    EMBEDDING_MODEL = _env_model
elif LOCAL_EMBEDDING_MODEL_DIR.is_dir() and (LOCAL_EMBEDDING_MODEL_DIR / "config.json").exists():
    EMBEDDING_MODEL = LOCAL_EMBEDDING_MODEL_DIR.as_posix()
else:
    EMBEDDING_MODEL = DEFAULT_EMBEDDING_MODEL
HF_TIMEOUT = int(
    os.getenv("HF_TIMEOUT", "600")
)  # Timeout for Hugging Face downloads (seconds)
HF_HOME = Path(os.getenv("HF_HOME", BASE_DIR / "storage" / "huggingface"))
_ensure_dir(HF_HOME)
_ensure_dir(LOCAL_EMBEDDING_MODEL_DIR.parent)
if "HF_HOME" not in os.environ:
    os.environ["HF_HOME"] = HF_HOME.as_posix()
if "HUGGINGFACE_HUB_CACHE" not in os.environ:
    os.environ["HUGGINGFACE_HUB_CACHE"] = (HF_HOME / "hub").as_posix()
if "TRANSFORMERS_CACHE" not in os.environ:
    os.environ["TRANSFORMERS_CACHE"] = (HF_HOME / "transformers").as_posix()
if "HF_HUB_DOWNLOAD_TIMEOUT" not in os.environ:
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = str(HF_TIMEOUT)
if "HF_HUB_DOWNLOAD_TIMEOUT_S" not in os.environ:
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT_S"] = str(HF_TIMEOUT)

# LLM selection
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

# Retrieval defaults
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

# Reranker
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").lower() == "true"
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Auth
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
# Required to change user plans via API (header: X-Plan-Admin-Secret)
PLAN_ADMIN_SECRET = os.getenv("PLAN_ADMIN_SECRET", "")

# CORS
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:8000",
).split(",")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"

# Rate Limiting
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

# Environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"
DOCS_ENABLED = os.getenv(
    "DOCS_ENABLED", "false" if IS_PRODUCTION else "true"
).lower() == "true"

# IP whitelist (off by default in production — public users need API access)
_default_ip_whitelist = "false" if IS_PRODUCTION else "true"
IP_WHITELIST_ENABLED = (
    os.getenv("IP_WHITELIST_ENABLED", _default_ip_whitelist).lower() == "true"
)

_default_allowed_ips = (
    "127.0.0.1,172.17.0.0/16,172.18.0.0/16,172.19.0.0/16"
)
_allowed_ips_env = os.getenv("ALLOWED_IPS", _default_allowed_ips)
ALLOWED_IPS: List[str] = [
    ip.strip() for ip in _allowed_ips_env.split(",") if ip.strip()
]

IP_WHITELIST_EXEMPT_PATHS = [
    "/health",
]
if DOCS_ENABLED:
    IP_WHITELIST_EXEMPT_PATHS.extend(["/docs", "/openapi.json", "/redoc"])
