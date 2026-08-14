"""Audit which priority labor/safety law titles appear in a docx folder or Chroma.

Usage:
  python scripts/audit_labor_safety_coverage.py --folder ../data-scrapping-law/outputs
  python scripts/audit_labor_safety_coverage.py --chroma storage/chroma
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Titles / phrases that should exist for strong workplace-accident answers
PRIORITY_PHRASES = [
    "قانون کار",
    "حفاظت فنی",
    "ایمنی",
    "تامین اجتماعی",
    "حوادث ناشی از کار",
    "بیمه اجباری کارگران ساختمانی",
    "بیمه مسئولیت",
    "کارگران ساختمانی",
    "آیین نامه ایمنی",
    "مسئولیت کارفرما",
]


def scan_folder(folder: Path) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {p: [] for p in PRIORITY_PHRASES}
    if not folder.is_dir():
        return hits
    for path in folder.rglob("*.docx"):
        name = path.name.replace("\u200c", " ")
        for phrase in PRIORITY_PHRASES:
            if phrase in name:
                hits[phrase].append(path.name)
    return hits


def scan_chroma(chroma_dir: Path, collection: str) -> dict[str, int]:
    from chromadb import PersistentClient

    client = PersistentClient(path=str(chroma_dir))
    col = client.get_collection(collection)
    # Sample metadata law_name / source via get (may be large — limit)
    data = col.get(include=["metadatas"], limit=50000)
    metas = data.get("metadatas") or []
    counts = {p: 0 for p in PRIORITY_PHRASES}
    for meta in metas:
        if not meta:
            continue
        blob = " ".join(
            str(meta.get(k) or "")
            for k in ("law_name", "source", "domain", "subdomain")
        )
        for phrase in PRIORITY_PHRASES:
            if phrase in blob:
                counts[phrase] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--folder",
        type=Path,
        default=BASE_DIR.parent / "data-scrapping-law" / "outputs",
    )
    parser.add_argument("--chroma", type=Path, default=None)
    parser.add_argument("--collection", default="legal-texts-v2")
    parser.add_argument(
        "--out",
        type=Path,
        default=BASE_DIR / "storage" / "labor_safety_coverage_audit.json",
    )
    args = parser.parse_args()

    report: dict = {
        "priority_phrases": PRIORITY_PHRASES,
        "folder": str(args.folder),
        "folder_hits": {},
        "folder_missing": [],
        "chroma_counts": None,
        "reingest_note": (
            "Ingest missing docs via scripts/ingest_outputs_watch.py or "
            "scripts/ingest_priority_laws.py, then re-enable "
            "ENABLE_DOMAIN_FILTERED_RETRIEVAL=true after taxonomy tags exist."
        ),
    }

    folder_hits = scan_folder(args.folder)
    report["folder_hits"] = {k: v[:20] for k, v in folder_hits.items()}
    report["folder_missing"] = [k for k, v in folder_hits.items() if not v]

    if args.chroma:
        report["chroma_counts"] = scan_chroma(args.chroma, args.collection)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Folder missing phrases:", report["folder_missing"] or "(none)")
    for phrase, files in folder_hits.items():
        status = f"{len(files)} file(s)" if files else "MISSING"
        print(f"  [{status}] {phrase}")
    if report["chroma_counts"] is not None:
        print("Chroma metadata hits (sampled):")
        for phrase, n in report["chroma_counts"].items():
            print(f"  [{n}] {phrase}")
    print(f"Wrote → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
