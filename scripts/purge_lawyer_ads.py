"""Find/deactivate sample PDFs that contain third-party lawyer advertisements.

Usage:
  python scripts/purge_lawyer_ads.py
  python scripts/purge_lawyer_ads.py --delete-files
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pypdf import PdfReader  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.sample_document import SampleDocument  # noqa: E402

DATA = ROOT / "data"
NEEDLES = [
    "موسی الرضا میر",
    "موسي الرضا مير",
    "مشاوره حقوقی با وکیل موسی",
    "وکیل موسی الرضا",
    "وکیل موسي الرضا",
]
FOLDERS = [
    "outputs_solh_contracts",
    "outputs_solh_petition",
    "outputs_solh_power_of_attorney",
    "outputs_solh_complaint",
    "outputs_solh_confirmation",
    "outputs_solh_declaration",
    "outputs_solh_company_statute",
    "outputs_prisoner_requests",
]


def pdf_has_ad(path: Path) -> str | None:
    try:
        reader = PdfReader(str(path))
        n = len(reader.pages)
        idxs = range(n) if n <= 6 else list(range(2)) + list(range(max(0, n - 2), n))
        text = ""
        for i in idxs:
            text += reader.pages[i].extract_text() or ""
        for needle in NEEDLES:
            if needle in text:
                return needle
    except Exception:
        return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete matching PDF files from disk",
    )
    args = parser.parse_args()

    hits: list[dict] = []
    for folder in FOLDERS:
        d = DATA / folder
        if not d.is_dir():
            continue
        for pdf in d.rglob("*.pdf"):
            matched = pdf_has_ad(pdf)
            if matched:
                rel = pdf.relative_to(DATA).as_posix()
                hits.append({"file_path": rel, "matched": matched})
                print(f"HIT {rel} ({matched})")

    db = SessionLocal()
    deactivated = 0
    try:
        for hit in hits:
            rows = (
                db.query(SampleDocument)
                .filter(SampleDocument.file_path == hit["file_path"])
                .all()
            )
            for row in rows:
                if row.is_active:
                    row.is_active = False
                    deactivated += 1
                    print(f"  deactivate id={row.id} title={row.title}")
            if args.delete_files:
                path = DATA / hit["file_path"]
                if path.is_file():
                    path.unlink()
                    print(f"  deleted {hit['file_path']}")
        db.commit()
    finally:
        db.close()

    report = {"hits": hits, "deactivated": deactivated}
    out = ROOT / "storage" / "_purge_lawyer_ads_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"hit_count": len(hits), "deactivated": deactivated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
