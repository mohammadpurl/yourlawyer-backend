"""Tests for monthly USD + free-tier usage quota (Redis reserve / adjust / release)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.user import PlanType
from app.services import quota as quota_mod
from app.services.quota import (
    QuotaExceeded,
    adjust_reservation,
    current_period,
    enforce_request_quota,
    quota_key,
    record_usage,
    release_reservation,
    reserve_cost,
    system_free_cost_key,
    user_cost_key,
    user_question_key,
)
from app.services.pricing import calculate_cost_usd, estimate_call_cost_usd


class FakeRedis:
    """Minimal Redis stand-in supporting GET / INCR / INCRBYFLOAT / EVAL / TTL / EXPIRE / SET."""

    def __init__(self):
        self.store: dict[str, float | str] = {}
        self.ttls: dict[str, int] = {}
        self._lock = __import__("threading").Lock()

    def get(self, key: str):
        if key not in self.store:
            return None
        return str(self.store[key])

    def incr(self, key: str):
        with self._lock:
            self.store[key] = float(self.store.get(key, 0.0)) + 1.0
            return int(self.store[key])

    def incrbyfloat(self, key: str, amount: float):
        with self._lock:
            self.store[key] = float(self.store.get(key, 0.0)) + float(amount)
            return self.store[key]

    def ttl(self, key: str):
        return self.ttls.get(key, -1)

    def expire(self, key: str, seconds: int):
        self.ttls[key] = int(seconds)
        return True

    def set(self, key: str, value, nx=False, ex=None):
        with self._lock:
            if nx and key in self.store:
                return False
            self.store[key] = value
            if ex is not None:
                self.ttls[key] = int(ex)
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
    monkeypatch.setattr(quota_mod, "FREE_USER_MONTHLY_COST_CAP", 0.08)
    monkeypatch.setattr(quota_mod, "FREE_MONTHLY_QUESTION_CAP", 5)
    monkeypatch.setattr(quota_mod, "SYSTEM_FREE_MONTHLY_CAP", 18.0)
    monkeypatch.setattr(quota_mod, "get_redis_client", lambda: client)
    return client


@pytest.fixture
def free_user(fake_redis):
    user = SimpleNamespace(id=42, plan_type=PlanType.FREE, questions_used=0)
    db = MagicMock()
    with patch.object(quota_mod, "get_or_create_user_quota", return_value=SimpleNamespace(max_cost_usd=Decimal("0.08"))):
        yield db, user


@pytest.fixture
def silver_user(fake_redis):
    user = SimpleNamespace(id=7, plan_type=PlanType.SILVER, questions_used=0)
    db = MagicMock()
    with patch.object(quota_mod, "get_or_create_user_quota", return_value=SimpleNamespace(max_cost_usd=Decimal("1.5"))):
        yield db, user


def test_user_quota_exceeded_raises_429(fake_redis, free_user):
    db, user = free_user
    fake_redis.store[user_cost_key(42)] = 0.075
    with pytest.raises(QuotaExceeded) as exc:
        reserve_cost(db, user, 0.01)
    assert exc.value.status_code == 429


def test_system_free_quota_exceeded_raises_503(fake_redis, free_user):
    db, user = free_user
    fake_redis.store[system_free_cost_key()] = 17.99
    with pytest.raises(QuotaExceeded) as exc:
        reserve_cost(db, user, 0.02)
    assert exc.value.status_code == 503
    # User reservation rolled back when system free fails
    assert float(fake_redis.store.get(user_cost_key(42), 0)) == pytest.approx(0.0)


def test_paid_user_not_subject_to_system_free(fake_redis, silver_user):
    db, user = silver_user
    fake_redis.store[system_free_cost_key()] = 18.0  # exhausted for free pool
    # Silver can still reserve against own 1.5 cap
    reserve_cost(db, user, 0.10)
    assert float(fake_redis.store[user_cost_key(7)]) == pytest.approx(0.10)
    # System free key untouched
    assert float(fake_redis.store[system_free_cost_key()]) == pytest.approx(18.0)


def test_paid_cap_429(fake_redis, silver_user):
    db, user = silver_user
    fake_redis.store[user_cost_key(7)] = 1.49
    with pytest.raises(QuotaExceeded) as exc:
        reserve_cost(db, user, 0.05)
    assert exc.value.status_code == 429


def test_concurrent_reserves_respect_limit(fake_redis, free_user):
    db, user = free_user
    monkey_cap = 0.30
    # Temporarily raise free cost cap for concurrency test via user quota path
    with patch("app.services.quota.cost_cap_for_plan", return_value=monkey_cap), patch(
        "app.services.quota.SYSTEM_FREE_MONTHLY_CAP", 10.0
    ):
        successes = []
        failures = []

        def attempt():
            try:
                reserve_cost(db, user, 0.10)
                successes.append(1)
            except QuotaExceeded:
                failures.append(1)

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: attempt(), range(6)))

        assert sum(successes) == 3
        assert sum(failures) == 3
        assert float(fake_redis.store[user_cost_key(42)]) == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_concurrent_asyncio_gather(fake_redis, free_user):
    db, user = free_user
    with patch("app.services.quota.cost_cap_for_plan", return_value=0.20), patch(
        "app.services.quota.SYSTEM_FREE_MONTHLY_CAP", 10.0
    ):

        async def attempt():
            await asyncio.to_thread(reserve_cost, db, user, 0.10)

        results = await asyncio.gather(
            attempt(), attempt(), attempt(), return_exceptions=True
        )
        ok = [r for r in results if not isinstance(r, Exception)]
        bad = [r for r in results if isinstance(r, QuotaExceeded)]
        assert len(ok) == 2
        assert len(bad) == 1


def test_release_on_openai_failure(fake_redis, free_user):
    db, user = free_user
    with patch("app.services.quota.cost_cap_for_plan", return_value=5.0), patch(
        "app.services.quota.SYSTEM_FREE_MONTHLY_CAP", 50.0
    ):
        reserve_cost(db, user, 0.12)
        assert float(fake_redis.store[user_cost_key(42)]) == pytest.approx(0.12)
        release_reservation("user", 42, 0.12)
        release_reservation("global", "system", 0.12)
        assert float(fake_redis.store[user_cost_key(42)]) == pytest.approx(0.0)
        assert float(fake_redis.store[system_free_cost_key()]) == pytest.approx(0.0)


def test_adjust_after_real_cost(fake_redis, free_user):
    db, user = free_user
    with patch("app.services.quota.cost_cap_for_plan", return_value=5.0), patch(
        "app.services.quota.SYSTEM_FREE_MONTHLY_CAP", 50.0
    ):
        reserve_cost(db, user, 0.20)
        adjust_reservation("user", 42, reserved=0.20, actual=0.05)
        assert float(fake_redis.store[user_cost_key(42)]) == pytest.approx(0.05)


def test_month_rollover_uses_new_key(fake_redis):
    p1 = "2026-06"
    p2 = "2026-07"
    k1 = user_cost_key(7, p1)
    k2 = user_cost_key(7, p2)
    fake_redis.store[k1] = 9.99
    assert fake_redis.get(k2) is None
    assert current_period()
    assert k1 != k2
    assert quota_key("user", 7, p1) == k1


def test_pricing_estimate_positive():
    cost = estimate_call_cost_usd("gpt-4o-mini", "سلام این یک متن تست است", 100)
    assert cost > 0
    exact = calculate_cost_usd("gpt-4o-mini", 1000, 500)
    assert exact > 0


def test_call_llm_releases_on_error(fake_redis, free_user, monkeypatch):
    from app.services import llm as llm_mod

    db, user = free_user
    monkeypatch.setattr(llm_mod, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm_mod, "QUOTA_ENABLED", True)

    with patch("app.services.quota.cost_cap_for_plan", return_value=5.0), patch(
        "app.services.quota.SYSTEM_FREE_MONTHLY_CAP", 50.0
    ):

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

        assert float(fake_redis.store.get(user_cost_key(42), 0.0)) == pytest.approx(0.0)
        assert float(fake_redis.store.get(system_free_cost_key(), 0.0)) == pytest.approx(
            0.0
        )


def test_enforce_free_upload_403(fake_redis, free_user):
    db, user = free_user
    with pytest.raises(HTTPException) as exc:
        enforce_request_quota(user, db, "document_review")
    assert exc.value.status_code == 403


def test_enforce_free_question_cap_429(fake_redis, free_user):
    db, user = free_user
    fake_redis.store[user_question_key(42)] = 5
    with pytest.raises(HTTPException) as exc:
        enforce_request_quota(user, db, "qa")
    assert exc.value.status_code == 429


def test_admin_exempt_from_quota(fake_redis, free_user):
    db, user = free_user
    user.is_admin = True
    fake_redis.store[user_question_key(42)] = 999
    fake_redis.store[user_cost_key(42)] = 999.0
    enforce_request_quota(user, db, "qa")  # no raise
    reserve_cost(db, user, 1.0)  # no raise


def test_get_quota_block_returns_message(fake_redis, free_user):
    db, user = free_user
    fake_redis.store[user_question_key(42)] = 5
    block = quota_mod.get_quota_block(user, db, "qa")
    assert block is not None
    assert block.status_code == 429
    assert "پلن رایگان" in block.message


def test_get_quota_block_none_for_admin(fake_redis, free_user):
    db, user = free_user
    user.is_admin = True
    fake_redis.store[user_question_key(42)] = 5
    assert quota_mod.get_quota_block(user, db, "qa") is None


def test_enforce_system_free_503(fake_redis, free_user):
    db, user = free_user
    fake_redis.store[system_free_cost_key()] = 18.0
    with pytest.raises(HTTPException) as exc:
        enforce_request_quota(user, db, "qa")
    assert exc.value.status_code == 503


def test_enforce_paid_upload_ok(fake_redis, silver_user):
    db, user = silver_user
    enforce_request_quota(user, db, "document_review")  # no raise


def test_record_usage_writes_cost_and_questions(fake_redis, free_user):
    db, user = free_user
    # Simulate prior adjust already put cost on redis
    fake_redis.store[user_cost_key(42)] = 0.012345
    fake_redis.store[system_free_cost_key()] = 0.012345

    # DB query chain stubs for monthly upserts
    db.query.return_value.filter.return_value.first.return_value = None

    record_usage(
        db,
        user=user,
        cost_usd=0.012345,
        request_type="qa",
        model="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50,
        request_id="req-1",
        count_question=True,
    )

    assert float(fake_redis.store[user_question_key(42)]) == pytest.approx(1.0)
    assert db.add.called
    assert db.commit.called


def test_check_quota_available_http(fake_redis, free_user):
    db, user = free_user
    fake_redis.store[user_cost_key(42)] = 0.08
    with pytest.raises(HTTPException) as exc:
        quota_mod.check_quota_available(db, user, estimated_usd=0.01)
    assert exc.value.status_code == 429
