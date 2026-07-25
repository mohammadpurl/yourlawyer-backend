"""Tests for monthly USD usage-quota (Redis reserve / adjust / release)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import quota as quota_mod
from app.services.quota import (
    QuotaExceeded,
    adjust_reservation,
    current_period,
    quota_key,
    release_reservation,
    reserve_cost,
)
from app.services.pricing import calculate_cost_usd, estimate_call_cost_usd


class FakeRedis:
    """Minimal Redis stand-in supporting GET / INCRBYFLOAT / EVAL / TTL / EXPIRE."""

    def __init__(self):
        self.store: dict[str, float] = {}
        self.ttls: dict[str, int] = {}
        self._lock = __import__("threading").Lock()

    def get(self, key: str):
        if key not in self.store:
            return None
        return str(self.store[key])

    def incrbyfloat(self, key: str, amount: float):
        with self._lock:
            self.store[key] = float(self.store.get(key, 0.0)) + float(amount)
            return self.store[key]

    def ttl(self, key: str):
        return self.ttls.get(key, -1)

    def expire(self, key: str, seconds: int):
        self.ttls[key] = int(seconds)
        return True

    def eval(self, script: str, numkeys: int, *args):
        with self._lock:
            key = args[0]
            delta = float(args[1])
            limit = float(args[2])
            ttl = int(float(args[3]))
            current = float(self.store.get(key, 0.0))
            cur_i = int(round(current * 1_000_000))
            delta_i = int(round(delta * 1_000_000))
            limit_i = int(round(limit * 1_000_000))
            if cur_i + delta_i > limit_i:
                return -1
            self.store[key] = current + delta
            if key not in self.ttls or self.ttls.get(key, -1) < 0:
                self.ttls[key] = ttl
            return self.store[key]

    def ping(self):
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(quota_mod, "QUOTA_ENABLED", True)
    monkeypatch.setattr(quota_mod, "QUOTA_FAIL_CLOSED", True)
    monkeypatch.setattr(quota_mod, "get_redis_client", lambda: client)
    return client


@pytest.fixture
def db_and_user(fake_redis):
    user = SimpleNamespace(id=42)
    global_q = SimpleNamespace(max_cost_usd=Decimal("1.00"), scope="global", user_id=None)
    user_q = SimpleNamespace(max_cost_usd=Decimal("0.50"), scope="user", user_id=42)
    db = MagicMock()

    def get_or_create_global(_db):
        return global_q

    def get_or_create_user(_db, user_id):
        assert user_id == 42
        return user_q

    with patch.object(quota_mod, "get_or_create_global_quota", get_or_create_global), patch.object(
        quota_mod, "get_or_create_user_quota", get_or_create_user
    ):
        yield db, user, global_q, user_q


def test_user_quota_exceeded_raises_429(fake_redis, db_and_user):
    db, user, _, user_q = db_and_user
    # Fill user bucket almost full
    fake_redis.store[quota_key("user", 42)] = 0.49
    with pytest.raises(QuotaExceeded) as exc:
        reserve_cost(db, user, 0.05)
    assert exc.value.status_code == 429
    assert "سقف مصرف ماهانه شما" in exc.value.message


def test_global_quota_exceeded_raises_503(fake_redis, db_and_user):
    db, user, global_q, user_q = db_and_user
    user_q.max_cost_usd = Decimal("10.00")
    fake_redis.store[quota_key("global", "system")] = 0.99
    with pytest.raises(QuotaExceeded) as exc:
        reserve_cost(db, user, 0.05)
    assert exc.value.status_code == 503
    assert "سقف مصرف کلی سامانه" in exc.value.message
    # User reservation must be rolled back when global fails
    assert fake_redis.store.get(quota_key("user", 42), 0) == 0.0


def test_concurrent_reserves_respect_limit(fake_redis, db_and_user):
    db, user, global_q, user_q = db_and_user
    user_q.max_cost_usd = Decimal("0.30")
    global_q.max_cost_usd = Decimal("10.00")

    successes = []
    failures = []

    def attempt():
        try:
            reserve_cost(db, user, 0.10)
            successes.append(1)
        except QuotaExceeded:
            failures.append(1)

    # Sync concurrency via threads is enough for FakeRedis atomicity in this process
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: attempt(), range(6)))

    assert sum(successes) == 3
    assert sum(failures) == 3
    assert fake_redis.store[quota_key("user", 42)] == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_concurrent_asyncio_gather(fake_redis, db_and_user):
    db, user, global_q, user_q = db_and_user
    user_q.max_cost_usd = Decimal("0.20")
    global_q.max_cost_usd = Decimal("10.00")

    async def attempt():
        await asyncio.to_thread(reserve_cost, db, user, 0.10)

    results = await asyncio.gather(
        attempt(), attempt(), attempt(), return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    bad = [r for r in results if isinstance(r, QuotaExceeded)]
    assert len(ok) == 2
    assert len(bad) == 1


def test_release_on_openai_failure(fake_redis, db_and_user):
    db, user, _, _ = db_and_user
    reserve_cost(db, user, 0.12)
    assert fake_redis.store[quota_key("user", 42)] == pytest.approx(0.12)
    release_reservation("user", 42, 0.12)
    release_reservation("global", "system", 0.12)
    assert fake_redis.store[quota_key("user", 42)] == pytest.approx(0.0)
    assert fake_redis.store[quota_key("global", "system")] == pytest.approx(0.0)


def test_adjust_after_real_cost(fake_redis, db_and_user):
    db, user, _, _ = db_and_user
    reserve_cost(db, user, 0.20)
    adjust_reservation("user", 42, reserved=0.20, actual=0.05)
    assert fake_redis.store[quota_key("user", 42)] == pytest.approx(0.05)


def test_month_rollover_uses_new_key(fake_redis):
    p1 = "2026-06"
    p2 = "2026-07"
    k1 = quota_key("user", 7, p1)
    k2 = quota_key("user", 7, p2)
    fake_redis.store[k1] = 9.99
    assert fake_redis.get(k2) is None
    assert current_period()  # YYYY-MM
    assert k1 != k2


def test_pricing_estimate_positive():
    cost = estimate_call_cost_usd("gpt-4o-mini", "سلام این یک متن تست است", 100)
    assert cost > 0
    exact = calculate_cost_usd("gpt-4o-mini", 1000, 500)
    assert exact > 0


def test_call_llm_releases_on_error(fake_redis, db_and_user, monkeypatch):
    from app.services import llm as llm_mod

    db, user, global_q, user_q = db_and_user
    user_q.max_cost_usd = Decimal("5.00")
    global_q.max_cost_usd = Decimal("50.00")

    monkeypatch.setattr(llm_mod, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm_mod, "QUOTA_ENABLED", True)

    class BoomLLM:
        def __init__(self, *a, **k):
            pass

        def invoke(self, messages):
            raise RuntimeError("openai down")

    monkeypatch.setattr(llm_mod, "ChatOpenAI", BoomLLM)

    with pytest.raises(RuntimeError):
        llm_mod.call_llm_with_quota_check(
            messages=[{"role": "user", "content": "hi"}],
            user=user,
            db=db,
            pipeline_stage="generate",
            max_completion_tokens=50,
        )

    assert fake_redis.store.get(quota_key("user", 42), 0.0) == pytest.approx(0.0)
    assert fake_redis.store.get(quota_key("global", "system"), 0.0) == pytest.approx(0.0)


def test_check_quota_available_http(fake_redis, db_and_user):
    db, user, _, user_q = db_and_user
    fake_redis.store[quota_key("user", 42)] = float(user_q.max_cost_usd)
    with pytest.raises(HTTPException) as exc:
        quota_mod.check_quota_available(db, user, estimated_usd=0.01)
    assert exc.value.status_code == 429
