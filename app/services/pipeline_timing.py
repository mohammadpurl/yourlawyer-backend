"""Lightweight pipeline stage timing for RAG bottleneck analysis.

Logs one JSON line per request (event=PIPELINE_TIMING) so timings can be
grepped/parsed even when LOG_FORMAT=plain.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4


class PipelineTimer:
    """Wall-clock stage timer using ``time.perf_counter()``."""

    def __init__(self, request_id: str | None = None):
        self.request_id = request_id or str(uuid4())
        self.timings: dict[str, float] = {}
        self.meta: dict[str, Any] = {}
        self._start = time.perf_counter()
        self._last = self._start

    def mark(self, stage: str) -> float:
        """Record ms since previous mark (or start) for ``stage``."""
        now = time.perf_counter()
        delta_ms = round((now - self._last) * 1000, 2)
        self.timings[stage] = delta_ms
        self._last = now
        return delta_ms

    def total_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 2)

    def set_meta(self, **kwargs: Any) -> None:
        self.meta.update({k: v for k, v in kwargs.items() if v is not None})

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": "PIPELINE_TIMING",
            "request_id": self.request_id,
            "stages": dict(self.timings),
            "total_ms": self.total_ms(),
            **self.meta,
        }

    def log_summary(self, logger: logging.Logger | None = None) -> dict[str, Any]:
        payload = self.as_dict()
        log = logger or logging.getLogger("app.pipeline_timing")
        # Prefix keeps plain-text logs searchable; body is JSON for parsers.
        log.info("PIPELINE_TIMING %s", json.dumps(payload, ensure_ascii=False))
        return payload
