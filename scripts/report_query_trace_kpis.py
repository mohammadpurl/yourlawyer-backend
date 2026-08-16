"""
Weekly KPI summary from QUERY_TRACE JSONL (layer-2 dashboard lite).

Usage:
  python scripts/report_query_trace_kpis.py
  python scripts/report_query_trace_kpis.py --path storage/query_traces.jsonl --tail 2000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def main() -> int:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    from app.core.config import BASE_DIR as APP_BASE

    default_path = Path(
        os.environ.get(
            "QUERY_TRACE_PATH",
            (APP_BASE / "storage" / "query_traces.jsonl").as_posix(),
        )
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=default_path)
    parser.add_argument("--tail", type=int, default=5000)
    parser.add_argument(
        "--out",
        type=Path,
        default=BASE_DIR / "storage" / "query_trace_kpi_report.json",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"No traces at {args.path}", file=sys.stderr)
        return 1

    lines = args.path.read_text(encoding="utf-8").splitlines()
    if args.tail:
        lines = lines[-args.tail :]

    outcomes: Counter[str] = Counter()
    refusals: Counter[str] = Counter()
    intents: Counter[str] = Counter()
    n = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        gen = row.get("generate") or {}
        outcomes[str(gen.get("outcome") or "unknown")] += 1
        if gen.get("refusal_reason"):
            refusals[str(gen["refusal_reason"])] += 1
        intent = (row.get("intent") or (row.get("extra") or {}).get("intent"))
        if intent:
            intents[str(intent)] += 1

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "path": str(args.path),
        "rows": n,
        "outcomes": dict(outcomes),
        "refusal_reasons": dict(refusals),
        "intents": dict(intents),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
