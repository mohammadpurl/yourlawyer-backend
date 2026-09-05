import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env before reading any settings (override stale shell exports).
load_dotenv(override=True)

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


# Active Chroma collection name (switch to legal-texts-v2 after clean rebuild)
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "legal-texts-v2")

# Storage directories
PERSIST_DIRECTORY = Path(
    os.getenv("CHROMA_DB_DIR", BASE_DIR / "storage" / "chroma")
).as_posix()
UPLOAD_DIRECTORY = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
_ensure_dir(UPLOAD_DIRECTORY)
AVATAR_DIRECTORY = Path(os.getenv("AVATAR_DIR", BASE_DIR / "storage" / "avatars"))
_ensure_dir(AVATAR_DIRECTORY)

# RAG: refuse to answer from model knowledge when Chroma returns no usable chunks
RAG_REQUIRE_RETRIEVED_CONTEXT = (
    os.getenv("RAG_REQUIRE_RETRIEVED_CONTEXT", "true").lower() == "true"
)
RAG_NO_CONTEXT_MESSAGE = os.getenv(
    "RAG_NO_CONTEXT_MESSAGE",
    "اطلاعات کافی در منابع موجود برای پاسخ دقیق به این سؤال یافت نشد.",
)

# Level-3 orientation when classify is confident but retrieval is empty/weak.
# Default off — enable only after manual review of sample outputs.
ENABLE_GENERAL_GUIDANCE_FALLBACK = (
    os.getenv("ENABLE_GENERAL_GUIDANCE_FALLBACK", "false").lower() == "true"
)
GENERAL_GUIDANCE_MIN_CLASSIFY_CONFIDENCE = float(
    os.getenv("GENERAL_GUIDANCE_MIN_CLASSIFY_CONFIDENCE", "0.6")
)

# Pre-RAG intent short-circuit (meta/greeting/out_of_scope → canned, no Chroma).
# Default true; set false for instant rollback.
ENABLE_INTENT_DETECTION = (
    os.getenv("ENABLE_INTENT_DETECTION", "true").lower() == "true"
)
INTENT_CACHE_TTL_SECONDS = int(os.getenv("INTENT_CACHE_TTL_SECONDS", "3600"))

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

# PII anonymization (before external LLM calls)
PII_ANONYMIZATION_ENABLED = (
    os.getenv("PII_ANONYMIZATION_ENABLED", "true").lower() == "true"
)
# Optional hazm-based NER for person names (off by default)
PII_NER_ENABLED = os.getenv("PII_NER_ENABLED", "false").lower() == "true"

# Retrieval defaults
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "8"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
# Cap prior chat turns sent to the LLM (user+assistant messages).
MAX_CHAT_HISTORY_MESSAGES = int(os.getenv("MAX_CHAT_HISTORY_MESSAGES", "8"))

# Reranker (CrossEncoder is CPU-heavy; disable via env for lower latency)
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").lower() == "true"
# Multilingual MS MARCO (Persian-capable). Old English MiniLM saturates ≈1.0 on FA.
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
)
# Drop chunks below this hybrid CE+keyword score before generate.
# mmarco hybrid scores for on-topic Persian law often land ~0.17–0.30 (not ~1.0).
# 0.40 refused good hits (e.g. طلاق توافقی / قانون حمایت خانواده at ~0.20).
MIN_SOURCE_RELEVANCE_SCORE = float(os.getenv("MIN_SOURCE_RELEVANCE_SCORE", "0.15"))

# Hierarchical taxonomy classify → Chroma metadata filter.
# Tried 2026-08-23 after domain-tag backfill brought unclassified from 33.3%
# to 19.33% (under the project's 20% gate for trying this). Measured net
# regression on the 120-question eval (answered 92->90, avg confidence
# 0.858->0.848, 2 questions lost their answer entirely) — domain tags are
# assigned at law/chunk granularity from law_name patterns, not per-passage
# topic, so restricting to same-domain chunks loses cross-document recall
# even when the classifier itself is correct. Rolled back to off; see
# eval/results/run_1787997358.json (domain filter ON) vs baseline_locked.json.
ENABLE_DOMAIN_FILTERED_RETRIEVAL = (
    os.getenv("ENABLE_DOMAIN_FILTERED_RETRIEVAL", "false").lower() == "true"
)
# Subdomain metadata is still sparse/noisy after law-name backfill; keep off by default.
ENABLE_SUBDOMAIN_FILTERED_RETRIEVAL = (
    os.getenv("ENABLE_SUBDOMAIN_FILTERED_RETRIEVAL", "false").lower() == "true"
)
TAXONOMY_CLASSIFY_MIN_CONFIDENCE = float(
    os.getenv("TAXONOMY_CLASSIFY_MIN_CONFIDENCE", "0.6")
)
# Use gpt-4o-mini for query classify (falls back to heuristic if no API key)
TAXONOMY_LLM_CLASSIFY = (
    os.getenv("TAXONOMY_LLM_CLASSIFY", "true").lower() == "true"
)

# Hybrid dense+BM25 retrieval (2026-08-23, evidence-driven): E5 dense search
# was confirmed (diagnostics on civil-013 "هبه" query) to miss exact legal-term
# matches entirely — the correct chunk didn't appear even in the top-200 dense
# results out of 179k chunks, despite existing verbatim in the corpus. BM25
# keyword search closes that gap for distinctive legal terms/article numbers.
# Enabled by explicit user request (2026-08-23) ahead of the original
# unclassified<20% gate — see eval/results/ comparisons before/after.
ENABLE_HYBRID_RETRIEVAL = (
    os.getenv("ENABLE_HYBRID_RETRIEVAL", "true").lower() == "true"
)
HYBRID_BM25_K = int(os.getenv("HYBRID_BM25_K", "8"))
# Optional LLM tagging during ingestion (expensive; default off → heuristic only)
USE_LLM_TAXONOMY_TAGGING = (
    os.getenv("USE_LLM_TAXONOMY_TAGGING", "false").lower() == "true"
)

# Auth
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Bootstrap admins by mobile (comma-separated). Grants permission admin.manage.
# Prefer this over a shared PLAN_ADMIN_SECRET header.
_admin_mobiles_raw = os.getenv("ADMIN_MOBILES", "")
ADMIN_MOBILES: List[str] = [
    m.strip() for m in _admin_mobiles_raw.split(",") if m.strip()
]

# CORS
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:8000",
).split(",")

# Redis (required when usage quota is enabled)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Usage quota (monthly USD cost ceilings + free-tier caps)
QUOTA_ENABLED = os.getenv("QUOTA_ENABLED", "true").lower() == "true"
QUOTA_FAIL_CLOSED = os.getenv("QUOTA_FAIL_CLOSED", "true").lower() == "true"
# Default Redis on when quota is on — counters live in Redis
REDIS_ENABLED = os.getenv(
    "REDIS_ENABLED", "true" if QUOTA_ENABLED else "false"
).lower() == "true"
# Legacy defaults (kept for admin/back-compat; free/paid caps below take precedence)
QUOTA_DEFAULT_GLOBAL_USD = float(os.getenv("QUOTA_DEFAULT_GLOBAL_USD", "18"))
QUOTA_DEFAULT_USER_USD = float(os.getenv("QUOTA_DEFAULT_USER_USD", "0.08"))

FREE_MONTHLY_QUESTION_CAP = int(os.getenv("FREE_MONTHLY_QUESTION_CAP", "5"))
FREE_USER_MONTHLY_COST_CAP = float(os.getenv("FREE_USER_MONTHLY_COST_CAP", "0.08"))
SYSTEM_FREE_MONTHLY_CAP = float(os.getenv("SYSTEM_FREE_MONTHLY_CAP", "18.0"))
PAID_SILVER_MONTHLY_COST_CAP = float(os.getenv("PAID_SILVER_MONTHLY_COST_CAP", "1.5"))
PAID_GOLD_MONTHLY_COST_CAP = float(os.getenv("PAID_GOLD_MONTHLY_COST_CAP", "4.0"))
SYSTEM_FREE_WARN_RATIO = float(os.getenv("SYSTEM_FREE_WARN_RATIO", "0.8"))
# ~40 days; also refreshed via seconds_until_next_month()
QUOTA_REDIS_TTL_SECONDS = int(os.getenv("QUOTA_REDIS_TTL_SECONDS", str(40 * 24 * 3600)))

DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")
LLM_MAX_COMPLETION_TOKENS = int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "1024"))

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
    # Public sample-document catalog (frontend SSR / guests)
    "/sample-documents",
]
if DOCS_ENABLED:
    IP_WHITELIST_EXEMPT_PATHS.extend(["/docs", "/openapi.json", "/redoc"])
