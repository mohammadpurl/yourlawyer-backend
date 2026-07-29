"""Import Solh sample PDF catalogs from data/outputs_solh_* into Postgres.

Usage (from repo root):
  python scripts/import_solh_catalog.py
  python scripts/import_solh_catalog.py --doc-type power_of_attorney
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal, Base, engine  # noqa: E402
import app.models.sample_document  # noqa: F401, E402
from app.models.sample_document import SampleDocument  # noqa: E402
from app.services.sample_documents import DOC_TYPE_META  # noqa: E402

DATA_ROOT = ROOT / "data"

# folder -> index filename
INDEX_FILES: dict[str, str] = {
    "outputs_solh_contracts": "contracts_index.json",
    "outputs_solh_petition": "petition_index.json",
    "outputs_solh_power_of_attorney": "power_of_attorney_index.json",
    "outputs_solh_complaint": "complaint_index.json",
    "outputs_solh_confirmation": "confirmation_index.json",
    "outputs_solh_declaration": "declaration_index.json",
    "outputs_solh_company_statute": "company_statute_index.json",
    "outputs_prisoner_requests": "prisoner_requests_index.json",
}


def _external_id(item: dict) -> str | None:
    for key in ("contract_id", "item_id", "id", "statute_id", "complaint_id"):
        if item.get(key) is not None:
            return str(item[key])
    return None


def _find_pdf(folder: Path, external_id: str) -> Path | None:
    """Match files named like ``{id}_....pdf``."""
    prefix = f"{external_id}_"
    exact = None
    for pdf in folder.rglob("*.pdf"):
        name = pdf.name
        if name.startswith(prefix):
            return pdf
        # rare: exact id.pdf
        if pdf.stem == external_id:
            exact = pdf
    return exact


def import_folder(db, *, doc_type: str, folder_name: str) -> dict:
    folder = DATA_ROOT / folder_name
    index_name = INDEX_FILES.get(folder_name)
    if not folder.is_dir() or not index_name:
        return {
            "doc_type": doc_type,
            "folder": folder_name,
            "error": "folder or index missing",
            "matched": 0,
            "missing": 0,
            "upserted": 0,
        }

    index_path = folder / index_name
    if not index_path.is_file():
        return {
            "doc_type": doc_type,
            "folder": folder_name,
            "error": f"index not found: {index_name}",
            "matched": 0,
            "missing": 0,
            "upserted": 0,
        }

    items = json.loads(index_path.read_text(encoding="utf-8"))
    matched = 0
    missing = 0
    upserted = 0
    missing_ids: list[str] = []

    for item in items:
        eid = _external_id(item)
        if not eid:
            missing += 1
            continue
        pdf = _find_pdf(folder, eid)
        if not pdf:
            missing += 1
            missing_ids.append(eid)
            continue

        matched += 1
        rel = pdf.relative_to(DATA_ROOT).as_posix()
        title = (item.get("title") or pdf.stem)[:500]
        category = (item.get("category") or "")[:200]
        source_url = item.get("url")

        row = (
            db.query(SampleDocument)
            .filter(
                SampleDocument.doc_type == doc_type,
                SampleDocument.external_id == eid,
            )
            .first()
        )
        if row:
            row.title = title
            row.category = category
            row.source_url = source_url
            row.file_path = rel
            row.is_active = True
        else:
            db.add(
                SampleDocument(
                    doc_type=doc_type,
                    external_id=eid,
                    title=title,
                    category=category,
                    source_url=source_url,
                    file_path=rel,
                    is_active=True,
                )
            )
        upserted += 1

    db.commit()
    return {
        "doc_type": doc_type,
        "folder": folder_name,
        "index_count": len(items),
        "matched": matched,
        "missing": missing,
        "upserted": upserted,
        "missing_ids_sample": missing_ids[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Solh sample document catalog")
    parser.add_argument(
        "--doc-type",
        default=None,
        help="Import only one doc_type (e.g. power_of_attorney)",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        reports = []
        for meta in DOC_TYPE_META:
            if args.doc_type and meta["doc_type"] != args.doc_type:
                continue
            report = import_folder(
                db, doc_type=meta["doc_type"], folder_name=meta["folder"]
            )
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False))
        summary = {
            "folders": len(reports),
            "matched": sum(r.get("matched", 0) for r in reports),
            "missing": sum(r.get("missing", 0) for r in reports),
            "upserted": sum(r.get("upserted", 0) for r in reports),
        }
        print(json.dumps({"summary": summary}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
