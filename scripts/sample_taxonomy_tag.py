"""Sample-tag docs with taxonomy metadata (validate before full re-ingest).

Usage:
  python scripts/sample_taxonomy_tag.py --folder "D:/.../outputs" --limit 30
  python scripts/sample_taxonomy_tag.py --name-contains کار,ایمنی,حادثه --limit 50
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Priority substrings for labor / workplace-safety corpus checks
LABOR_SAFETY_KEYWORDS = (
    "کار",
    "ایمنی",
    "حادثه",
    "حفاظت",
    "تامین اجتماعی",
    "ساختمان",
    "کارفرما",
    "بیمه مسئولیت",
)


def _matches_filters(name: str, contains: list[str]) -> bool:
    if not contains:
        return True
    lower = name.replace("\u200c", " ")
    return any(c in lower for c in contains if c)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sample-tag docx files with hierarchical taxonomy"
    )
    parser.add_argument(
        "--folder",
        type=Path,
        default=BASE_DIR.parent / "data-scrapping-law" / "outputs",
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--out",
        type=Path,
        default=BASE_DIR / "storage" / "taxonomy_sample_tag_report.json",
    )
    parser.add_argument(
        "--name-contains",
        type=str,
        default="",
        help="Comma-separated filename substrings to prefer (e.g. کار,ایمنی,حادثه)",
    )
    parser.add_argument(
        "--labor-safety",
        action="store_true",
        help="Shorthand: filter filenames with labor/safety keywords",
    )
    args = parser.parse_args()

    from app.services.ingestion import load_text_from_file, _tag_taxonomy

    contains: list[str] = []
    if args.labor_safety:
        contains.extend(LABOR_SAFETY_KEYWORDS)
    if args.name_contains.strip():
        contains.extend(
            p.strip() for p in args.name_contains.split(",") if p.strip()
        )

    all_files = sorted(p for p in args.folder.rglob("*.docx") if p.is_file())
    if contains:
        preferred = [p for p in all_files if _matches_filters(p.name, contains)]
        other = [p for p in all_files if p not in preferred]
        files = (preferred + other)[: args.limit]
        print(
            f"Filter keywords={contains!r} | matched={len(preferred)} | "
            f"sampling={len(files)}"
        )
    else:
        files = all_files[: args.limit]

    rows = []
    for f in files:
        try:
            text = load_text_from_file(f)
            tag = _tag_taxonomy(f.name, text)
            rows.append(
                {
                    "file": f.name,
                    "domain": tag.get("domain"),
                    "subdomain": tag.get("subdomain"),
                    "confidence": tag.get("confidence"),
                    "method": tag.get("method"),
                }
            )
            print(
                f"{tag.get('domain')}/{tag.get('subdomain')}  "
                f"conf={tag.get('confidence')}  {f.name[:60]}"
            )
        except Exception as e:
            rows.append({"file": f.name, "error": str(e)})
            print(f"ERROR {f.name}: {e}")

    domain_counts = Counter(r.get("domain") for r in rows if "error" not in r)
    subdomain_counts = Counter(
        f"{r.get('domain')}/{r.get('subdomain')}" for r in rows if "error" not in r
    )
    summary = {
        "sampled": len(rows),
        "domain_counts": dict(domain_counts),
        "subdomain_counts": dict(subdomain_counts),
        "rows": rows,
        "note": (
            "After validating tags, re-ingest with current taxonomy metadata, "
            "then set ENABLE_DOMAIN_FILTERED_RETRIEVAL=true"
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(rows)} rows → {args.out}")
    print("domain_counts:", dict(domain_counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
