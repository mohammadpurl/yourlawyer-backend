"""Load LLM pricing from JSON (no hardcoded business prices in call sites)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRICING_PATH = Path(__file__).resolve().parent.parent / "config" / "llm_pricing.json"


@lru_cache(maxsize=1)
def load_pricing() -> dict[str, Any]:
    try:
        with _PRICING_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load LLM pricing config: %s", e)
        return {
            "models": {},
            "default_model": "gpt-4o-mini",
            "fallback": {"input": 1.0, "output": 3.0},
        }


def reload_pricing() -> dict[str, Any]:
    load_pricing.cache_clear()
    return load_pricing()


def get_model_rates(model: str) -> tuple[float, float]:
    """Return (input_usd_per_1m, output_usd_per_1m) for a model."""
    cfg = load_pricing()
    models = cfg.get("models") or {}
    rates = models.get(model) or models.get(cfg.get("default_model")) or cfg.get(
        "fallback", {"input": 1.0, "output": 3.0}
    )
    return float(rates["input"]), float(rates["output"])


def estimate_tokens_from_text(text: str) -> int:
    """Conservative token estimate (Persian-heavy text ≈ ~2 chars/token)."""
    if not text:
        return 1
    return max(1, (len(text) + 1) // 2)


def calculate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    inp, out = get_model_rates(model)
    return (prompt_tokens / 1_000_000.0) * inp + (completion_tokens / 1_000_000.0) * out


def estimate_call_cost_usd(
    model: str,
    prompt_text: str,
    max_completion_tokens: int = 1024,
    safety_multiplier: float = 1.25,
) -> float:
    prompt_tokens = estimate_tokens_from_text(prompt_text)
    raw = calculate_cost_usd(model, prompt_tokens, max_completion_tokens)
    return round(raw * safety_multiplier, 6)
