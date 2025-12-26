"""Redis caching utilities for RAG results and embeddings."""

import json
import hashlib
from typing import Optional, Any
import logging

from app.core.config import REDIS_URL, REDIS_ENABLED

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client():
    """Get or create Redis client."""
    global _redis_client
    if not REDIS_ENABLED:
        return None
    
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            # Test connection
            _redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis not available: {e}. Caching disabled.")
            return None
    
    return _redis_client


def _make_key(prefix: str, *args) -> str:
    """Create a cache key from prefix and arguments."""
    key_str = ":".join(str(arg) for arg in args)
    # Hash long keys to avoid Redis key length issues
    if len(key_str) > 200:
        key_str = hashlib.sha256(key_str.encode()).hexdigest()
    return f"{prefix}:{key_str}"


def cache_get(key_prefix: str, *key_args) -> Optional[Any]:
    """Get value from cache."""
    if not REDIS_ENABLED:
        return None
    
    client = get_redis_client()
    if not client:
        return None
    
    try:
        key = _make_key(key_prefix, *key_args)
        value = client.get(key)
        if value:
            return json.loads(value)
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
    
    return None


def cache_set(key_prefix: str, value: Any, ttl: int = 3600, *key_args):
    """Set value in cache with TTL."""
    if not REDIS_ENABLED:
        return
    
    client = get_redis_client()
    if not client:
        return
    
    try:
        key = _make_key(key_prefix, *key_args)
        client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Cache set error: {e}")


def cache_delete(key_prefix: str, *key_args):
    """Delete value from cache."""
    if not REDIS_ENABLED:
        return
    
    client = get_redis_client()
    if not client:
        return
    
    try:
        key = _make_key(key_prefix, *key_args)
        client.delete(key)
    except Exception as e:
        logger.warning(f"Cache delete error: {e}")


def cache_rag_result(question: str, top_k: int, use_enhanced: bool, result: dict, ttl: int = 3600):
    """Cache RAG result."""
    cache_set("rag:result", result, ttl, question, top_k, use_enhanced)


def get_cached_rag_result(question: str, top_k: int, use_enhanced: bool) -> Optional[dict]:
    """Get cached RAG result."""
    return cache_get("rag:result", question, top_k, use_enhanced)


def cache_embedding(text: str, embedding: list, ttl: int = 86400):
    """Cache embedding vector."""
    cache_set("embedding", embedding, ttl, text)


def get_cached_embedding(text: str) -> Optional[list]:
    """Get cached embedding."""
    return cache_get("embedding", text)


def cache_classification(question: str, domain: str, confidence: float, ttl: int = 3600):
    """Cache question classification."""
    cache_set("classification", {"domain": domain, "confidence": confidence}, ttl, question)


def get_cached_classification(question: str) -> Optional[dict]:
    """Get cached classification."""
    return cache_get("classification", question)



