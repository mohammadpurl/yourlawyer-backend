"""Unit tests for PipelineTimer (no LLM / Chroma required)."""

from __future__ import annotations

import json
import logging
import time

from app.services.pipeline_timing import PipelineTimer


def test_pipeline_timer_marks_stages():
    t = PipelineTimer(request_id="req-test")
    time.sleep(0.01)
    t.mark("classify")
    time.sleep(0.02)
    t.mark("retrieve")
    t.set_meta(retrieved_count=8, model="gpt-4o-mini")

    assert t.timings["classify"] >= 5
    assert t.timings["retrieve"] >= 10
    assert t.total_ms() >= t.timings["classify"] + t.timings["retrieve"] - 1
    payload = t.as_dict()
    assert payload["event"] == "PIPELINE_TIMING"
    assert payload["request_id"] == "req-test"
    assert payload["retrieved_count"] == 8
    assert payload["model"] == "gpt-4o-mini"


def test_pipeline_timer_log_summary_is_json(caplog):
    t = PipelineTimer(request_id="abc")
    t.mark("generate")
    t.set_meta(prompt_tokens=10, completion_tokens=5)

    logger = logging.getLogger("test.pipeline_timing")
    with caplog.at_level(logging.INFO, logger="test.pipeline_timing"):
        t.log_summary(logger)

    assert any("PIPELINE_TIMING" in r.message for r in caplog.records)
    msg = next(r.message for r in caplog.records if "PIPELINE_TIMING" in r.message)
    json_part = msg.split("PIPELINE_TIMING", 1)[1].strip()
    data = json.loads(json_part)
    assert data["event"] == "PIPELINE_TIMING"
    assert "generate" in data["stages"]
    assert data["prompt_tokens"] == 10
