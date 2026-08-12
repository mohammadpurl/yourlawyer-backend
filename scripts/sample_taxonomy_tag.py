"""Sample-tag ~30 docs with taxonomy metadata (validate before full re-ingest).

Usage:
  python scripts/sample_taxonomy_tag.py --folder "D:/.../outputs" --limit 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def main() -> int:
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()

    from app.services.ingestion import load_text_from_file, _tag_taxonomy

    files = sorted(p for p in args.folder.rglob("*.docx") if p.is_file())[: args.limit]
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

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(rows)} rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
