import os
from pathlib import Path
from typing import List

# Hugging Face Hub settings must be set before huggingface_hub is imported anywhere.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")


BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Storage directories
PERSIST_DIRECTORY = Path(
    os.getenv("CHROMA_DB_DIR", BASE_DIR / "storage" / "chroma")
).as_posix()
UPLOAD_DIRECTORY = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)

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
HF_HOME.mkdir(parents=True, exist_ok=True)
LOCAL_EMBEDDING_MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
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

# لیست IPهای مجاز (می‌تواند IP دقیق یا subnet باشد)
ALLOWED_IPS: List[str] = [
    "127.0.0.1",  # localhost
    "37.59.183.158",  # IP سرور فرانت اصلی
    "172.17.0.0/16",  # subnet پیش‌فرض docker
    "172.18.0.0/16",  # subnet پروژه شما (از لاگ دیدم)
    "172.19.0.0/16",  # subnet اضافی اگر نیاز بود
    "178.131.95.38",  # IP خودت برای تست از بیرون
    # اگر IPهای دیگری (مثل IP خانه یا دفتر) داری، اینجا اضافه کن
]

IP_WHITELIST_ENABLED = True  # فعال نگه دار
IP_WHITELIST_EXEMPT_PATHS = [
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
]  # مسیرهای مستثنی (که بدون چک IP کار کنند)
