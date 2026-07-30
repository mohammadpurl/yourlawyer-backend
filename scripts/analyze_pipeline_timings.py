"""Analyze PIPELINE_TIMING log lines (mean / median / p95 per stage).

Usage:
  python scripts/analyze_pipeline_timings.py path/to/app.log
  docker logs backend 2>&1 | python scripts/analyze_pipeline_timings.py -
  python scripts/analyze_pipeline_timings.py app.log --last 200
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _extract_payload(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if "PIPELINE_TIMING" not in line:
        return None
    # Prefer JSON after the marker
    marker = "PIPELINE_TIMING"
    idx = line.find(marker)
    rest = line[idx + len(marker) :].strip()
    if rest.startswith("{"):
        try:
            data = json.loads(rest)
            if data.get("event") == "PIPELINE_TIMING" or "stages" in data:
                return data
        except json.JSONDecodeError:
            pass
    # Whole line JSON
    if line.startswith("{"):
        try:
            data = json.loads(line)
            if data.get("event") == "PIPELINE_TIMING":
                return data
        except json.JSONDecodeError:
            return None
    return None


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0, "median": 0, "p95": 0, "max": 0}
    s = sorted(values)
    return {
        "count": len(s),
        "mean": round(sum(s) / len(s), 2),
        "median": round(_percentile(s, 50), 2),
        "p95": round(_percentile(s, 95), 2),
        "max": round(s[-1], 2),
    }


def iter_lines(path: str) -> Iterable[str]:
    if path == "-":
        yield from sys.stdin
        return
    with Path(path).open("r", encoding="utf-8", errors="replace") as f:
        yield from f


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze PIPELINE_TIMING logs")
    parser.add_argument("log_path", help="Log file path, or '-' for stdin")
    parser.add_argument(
        "--last", type=int, default=0, help="Only use the last N matching events"
    )
    args = parser.parse_args()

    events: list[dict[str, Any]] = []
    for line in iter_lines(args.log_path):
        payload = _extract_payload(line)
        if payload:
            events.append(payload)

    if args.last and args.last > 0:
        events = events[-args.last :]

    if not events:
        print("No PIPELINE_TIMING events found.", file=sys.stderr)
        return 1

    stage_values: dict[str, list[float]] = defaultdict(list)
    totals: list[float] = []
    retrieved: list[float] = []
    for ev in events:
        stages = ev.get("stages") or {}
        if isinstance(stages, dict):
            for name, ms in stages.items():
                try:
                    stage_values[str(name)].append(float(ms))
                except (TypeError, ValueError):
                    pass
        try:
            totals.append(float(ev.get("total_ms") or 0))
        except (TypeError, ValueError):
            pass
        if ev.get("retrieved_count") is not None:
            try:
                retrieved.append(float(ev["retrieved_count"]))
            except (TypeError, ValueError):
                pass

    print(f"events={len(events)}")
    print("--- stages (ms) ---")
    preferred = ["anonymize", "cache_lookup", "classify", "retrieve", "rerank", "generate"]
    seen = set()
    for name in preferred + sorted(stage_values.keys()):
        if name in seen or name not in stage_values:
            continue
        seen.add(name)
        stats = _summarize(stage_values[name])
        print(
            f"{name:14} n={stats['count']:4}  mean={stats['mean']:8.2f}  "
            f"median={stats['median']:8.2f}  p95={stats['p95']:8.2f}  max={stats['max']:8.2f}"
        )

    print("--- total_ms ---")
    t = _summarize(totals)
    print(
        f"{'total':14} n={t['count']:4}  mean={t['mean']:8.2f}  "
        f"median={t['median']:8.2f}  p95={t['p95']:8.2f}  max={t['max']:8.2f}"
    )
    if retrieved:
        r = _summarize(retrieved)
        print("--- retrieved_count ---")
        print(
            f"{'retrieved':14} n={r['count']:4}  mean={r['mean']:8.2f}  "
            f"median={r['median']:8.2f}  p95={r['p95']:8.2f}  max={r['max']:8.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
