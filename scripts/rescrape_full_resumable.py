"""
Resumable two-tier rescrape: criminal priority first, then remaining corpus IDs.

Download/validate only — does NOT ingest into Chroma.

Usage:
  python scripts/rescrape_full_resumable.py --plan-only
  python scripts/rescrape_full_resumable.py --start --criminal-only
  python scripts/rescrape_full_resumable.py --start
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRAPER_DIR = BASE_DIR.parent / "data-scrapping-law"
CHECKPOINT = BASE_DIR / "storage" / "full_rescrape_checkpoint.json"
STATUS = BASE_DIR / "storage" / "rescrape_status.json"
CRIMINAL_IDS = SCRAPER_DIR / "criminal_priority_ids.json"
DEFAULT_OUTPUT = SCRAPER_DIR / "outputs_clean"
CRIMINAL_OUTPUT = SCRAPER_DIR / "outputs_criminal"
DEFAULT_DELAY = 2.5
SCRAPER = SCRAPER_DIR / "scrape_qavanin.py"


def estimate_hours(n_files: int, delay: float, overhead: float = 8.0) -> float:
    seconds = n_files * (delay + overhead)
    return round(seconds / 3600.0, 1)


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def plan(n_remaining: int = 24186, delay: float = DEFAULT_DELAY) -> dict:
    criminal = load_json(CRIMINAL_IDS, {})
    n_criminal = len(criminal.get("ids") or [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tiers": {
            "1_criminal_priority": {
                "count": n_criminal,
                "ids_file": str(CRIMINAL_IDS),
                "output_dir": str(CRIMINAL_OUTPUT),
                "estimated_hours": estimate_hours(n_criminal, delay),
            },
            "2_full_corpus": {
                "remaining_files_estimate": n_remaining,
                "output_dir": str(DEFAULT_OUTPUT),
                "estimated_hours": estimate_hours(n_remaining, delay),
                "estimated_days_8h": round(estimate_hours(n_remaining, delay) / 8.0, 1),
            },
        },
        "delay_seconds": delay,
        "checkpoint_path": str(CHECKPOINT),
        "status_path": str(STATUS),
        "ingest_policy": "Download only. Ingest to legal-texts-v2 requires explicit approval.",
        "notes": [
            "Tier 1 (criminal) runs before the general 24k queue",
            "Use --criminal-only to stop after tier 1",
            "Never fall back to shared local HTML test files",
            "Check progress: python scripts/check_rescrape_progress.py",
        ],
    }


def _completed_set(ckpt: dict) -> set[str]:
    return set(str(x) for x in (ckpt.get("completed_ids") or []))


def _mark_done(ckpt: dict, law_id: str, path: str | None, tier: str) -> None:
    ckpt.setdefault("completed_ids", [])
    if law_id not in ckpt["completed_ids"]:
        ckpt["completed_ids"].append(law_id)
    ckpt.setdefault("items", {})[law_id] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "path": path,
        "tier": tier,
    }
    ckpt["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(CHECKPOINT, ckpt)


def _write_status(**kwargs) -> None:
    data = load_json(STATUS, {})
    data.update(kwargs)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(STATUS, data)


def _run_ids_file(
    ids_file: Path,
    output_dir: Path,
    delay: float,
    *,
    tier: str,
    force: bool = True,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(SCRAPER),
        "--use-selenium",
        "--delay",
        str(delay),
        "--output-dir",
        str(output_dir),
        "--ids-file",
        str(ids_file),
    ]
    if force:
        cmd.append("--force")
    _write_status(
        phase=tier,
        running=True,
        command=" ".join(cmd),
        output_dir=str(output_dir),
        ids_file=str(ids_file),
    )
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(SCRAPER_DIR))
    return proc.returncode


def run_criminal(delay: float, force: bool) -> int:
    criminal = load_json(CRIMINAL_IDS, {})
    ids = [str(x) for x in (criminal.get("ids") or [])]
    ckpt = load_json(CHECKPOINT, {"completed_ids": [], "items": {}})
    done = _completed_set(ckpt)
    pending = [i for i in ids if i not in done]
    _write_status(
        phase="criminal_priority",
        running=True,
        criminal_total=len(ids),
        criminal_pending=len(pending),
        criminal_done=len(ids) - len(pending),
        estimated_hours_remaining=estimate_hours(len(pending), delay),
    )
    if not pending:
        print("[criminal] all priority IDs already in checkpoint")
        return 0

    # Write a temp ids-file with only pending
    pending_file = BASE_DIR / "storage" / "criminal_pending_ids.json"
    save_json(
        pending_file,
        {
            "ids": pending,
            "titles": {
                k: v
                for k, v in (criminal.get("titles") or {}).items()
                if k in pending
            },
        },
    )
    rc = _run_ids_file(
        pending_file, CRIMINAL_OUTPUT, delay, tier="criminal_priority", force=force
    )
    # Mark any new docx titles mapped back by id via titles map
    titles = criminal.get("titles") or {}
    for law_id in pending:
        title = titles.get(law_id, "")
        matches = list(CRIMINAL_OUTPUT.glob(f"*{title[:20]}*.docx")) if title else []
        id_matches = list(CRIMINAL_OUTPUT.glob(f"{law_id}*.docx"))
        found = (matches or id_matches)
        if found:
            _mark_done(ckpt, law_id, str(found[0]), "criminal_priority")
    _write_status(
        phase="criminal_priority",
        running=False,
        last_exit_code=rc,
        criminal_done=len(_completed_set(load_json(CHECKPOINT, {})) & set(ids)),
    )
    return rc


def run_full_batches(delay: float, force: bool, batch_file: Path | None) -> int:
    """Optional second tier: process a provided remaining-ids file in one go."""
    if not batch_file or not batch_file.exists():
        print(
            "[full] no --remaining-ids-file provided; criminal tier only. "
            "Pass a JSON/TXT of remaining IDS when ready for tier 2."
        )
        _write_status(phase="idle", running=False, message="awaiting remaining-ids-file")
        return 0
    return _run_ids_file(
        batch_file, DEFAULT_OUTPUT, delay, tier="full_corpus", force=force
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--start", action="store_true", help="Start rescrape workers")
    parser.add_argument("--criminal-only", action="store_true", default=True)
    parser.add_argument("--include-full", action="store_true", help="Also run tier 2 if ids file given")
    parser.add_argument("--remaining-ids-file", type=Path, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--remaining", type=int, default=24186)
    parser.add_argument("--force", action="store_true", default=True)
    args = parser.parse_args()

    report = plan(args.remaining, args.delay)
    out = BASE_DIR / "storage" / "full_rescrape_plan.json"
    save_json(out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Wrote {out}")

    if args.plan_only or not args.start:
        return 0

    rc = run_criminal(args.delay, args.force)
    if rc != 0:
        return rc
    if args.include_full:
        return run_full_batches(args.delay, args.force, args.remaining_ids_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
