"""Show rescrape progress anytime.

Usage:
  python scripts/check_rescrape_progress.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRAPER_DIR = BASE_DIR.parent / "data-scrapping-law"
STATUS = BASE_DIR / "storage" / "rescrape_status.json"
CHECKPOINT = BASE_DIR / "storage" / "full_rescrape_checkpoint.json"
CRIMINAL_IDS = SCRAPER_DIR / "criminal_priority_ids.json"
CRIMINAL_OUTPUT = SCRAPER_DIR / "outputs_criminal"
CLEAN_OUTPUT = SCRAPER_DIR / "outputs_clean"
LOG = BASE_DIR / "storage" / "rescrape_criminal.log"


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _count_docx(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for _ in folder.glob("*.docx"))


def main() -> int:
    criminal = _load(CRIMINAL_IDS, {})
    ids = [str(x) for x in (criminal.get("ids") or [])]
    ckpt = _load(CHECKPOINT, {"completed_ids": []})
    status = _load(STATUS, {})
    done = set(str(x) for x in (ckpt.get("completed_ids") or []))
    criminal_done = [i for i in ids if i in done]
    criminal_pending = [i for i in ids if i not in done]

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "running": bool(status.get("running")),
        "phase": status.get("phase"),
        "criminal": {
            "total": len(ids),
            "done": len(criminal_done),
            "pending": len(criminal_pending),
            "pending_ids": criminal_pending,
            "docx_on_disk": _count_docx(CRIMINAL_OUTPUT),
            "output_dir": str(CRIMINAL_OUTPUT),
            "est_hours_if_pending_at_2_5s": round(
                len(criminal_pending) * (2.5 + 8.0) / 3600.0, 2
            ),
        },
        "full_corpus": {
            "docx_on_disk": _count_docx(CLEAN_OUTPUT),
            "output_dir": str(CLEAN_OUTPUT),
            "checkpoint_completed_total": len(done),
        },
        "status_file": status,
        "log_exists": LOG.exists(),
        "log_path": str(LOG),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
