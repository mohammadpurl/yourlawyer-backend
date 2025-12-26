"""Tests for caching functionality."""

import pytest
from app.core.cache import cache_set, cache_get, cache_delete, get_redis_client


def test_cache_basic():
    """Test basic cache operations."""
    # Skip if Redis not enabled
    client = get_redis_client()
    if not client:
        pytest.skip("Redis not enabled")
    
    # Test set and get
    cache_set("test", "value", 60, "key1", "key2")
    result = cache_get("test", "key1", "key2")
    assert result == "value"
    
    # Test delete
    cache_delete("test", "key1", "key2")
    result = cache_get("test", "key1", "key2")
    assert result is None


def test_cache_rag_result():
    """Test RAG result caching."""
    from app.core.cache import cache_rag_result, get_cached_rag_result
    
    client = get_redis_client()
    if not client:
        pytest.skip("Redis not enabled")
    
    question = "سوال تست"
    result = {"answer": "پاسخ تست", "sources": []}
    
    cache_rag_result(question, 5, True, result, ttl=60)
    cached = get_cached_rag_result(question, 5, True)
    
    assert cached == result



