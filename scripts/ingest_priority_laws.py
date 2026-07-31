"""
Ingest priority (clean) laws into a fresh Chroma collection.

Usage:
  python scripts/ingest_priority_laws.py
  python scripts/ingest_priority_laws.py --folder ../data-scrapping-law/outputs_priority
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.config import CHROMA_COLLECTION, PERSIST_DIRECTORY  # noqa: E402
from app.services.ingestion import chunk_text, load_text_from_file  # noqa: E402
from app.services.vectorstore import (  # noqa: E402
    add_documents,
    ensure_embeddings_ready,
    stats,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--folder",
        type=Path,
        default=BASE_DIR.parent / "data-scrapping-law" / "outputs_priority",
    )
    parser.add_argument("--collection", default=CHROMA_COLLECTION)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    folder: Path = args.folder
    if not folder.is_absolute():
        folder = (BASE_DIR / folder).resolve()
    if not folder.exists():
        logging.error("Folder not found: %s", folder)
        return 1

    ensure_embeddings_ready()
    files = sorted(folder.glob("*.docx"))
    logging.info("Ingesting %s files into collection=%s dir=%s", len(files), args.collection, PERSIST_DIRECTORY)

    all_docs = []
    rejected = 0
    for f in files:
        text = load_text_from_file(f)
        docs = chunk_text(text, source=f.name)
        if not docs:
            rejected += 1
            logging.warning("Rejected/empty after validation: %s", f.name)
            continue
        all_docs.extend(docs)
        logging.info("%s -> %s chunks", f.name, len(docs))

    added = add_documents(all_docs, collection_name=args.collection)
    st = stats(args.collection)
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "collection": args.collection,
        "files": len(files),
        "rejected_files": rejected,
        "chunks_prepared": len(all_docs),
        "chunks_added": added,
        "stats": st,
    }
    out = BASE_DIR / "storage" / "priority_ingest_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Report: %s", json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
