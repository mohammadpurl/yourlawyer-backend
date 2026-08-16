"""
Pilot / validate-then-ingest criminal-priority laws (layer-1 roadmap).

Default folder: ``data/outputs_criminal`` (DOCX/PDF).
Uses the same quality gate as work-law ingest (pymupdf + NFKC for PDF;
DOCX via python-docx). Forces taxonomy domain ``کیفری`` when heuristic is weak
(except چک → commercial via map).

Usage:
  python scripts/ingest_criminal_pilot.py --dry-run
  python scripts/ingest_criminal_pilot.py --limit 2
  python scripts/ingest_criminal_pilot.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_FOLDER = BASE_DIR / "data" / "outputs_criminal"
DEFAULT_CHROMA = BASE_DIR / "storage" / "chroma_clean"
CHECKPOINT = BASE_DIR / "storage" / "criminal_pilot_checkpoint.json"
REPORT = BASE_DIR / "storage" / "criminal_pilot_ingest_report.json"

SUPPORTED = {".pdf", ".docx", ".doc", ".txt", ".md"}
CRIMINAL_DOMAIN = "کیفری"


def _load_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Pilot criminal law pilot ingest")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument(
        "--chroma-dir",
        type=Path,
        default=Path(os.environ.get("CHROMA_DB_DIR", str(DEFAULT_CHROMA))),
    )
    parser.add_argument(
        "--collection",
        default=os.environ.get("CHROMA_COLLECTION", "legal-texts-v2"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    folder = args.folder if args.folder.is_absolute() else (BASE_DIR / args.folder).resolve()
    if not folder.exists():
        logging.error("Folder not found: %s", folder)
        return 1

    chroma_dir = args.chroma_dir
    if not chroma_dir.is_absolute():
        chroma_dir = (BASE_DIR / chroma_dir).resolve()
    if not args.dry_run:
        chroma_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CHROMA_DB_DIR"] = str(chroma_dir).replace("\\", "/")
        os.environ["CHROMA_COLLECTION"] = args.collection

    from app.services.domain_law_map import map_law_to_domain
    from app.services.ingestion import (
        assess_extracted_text_quality,
        chunk_text,
        load_text_from_file,
    )

    if not args.dry_run:
        from app.services.vectorstore import add_documents, ensure_embeddings_ready, stats

        ensure_embeddings_ready()
        logging.info("stats=%s", stats(args.collection))

    if args.reset_checkpoint and CHECKPOINT.exists():
        CHECKPOINT.unlink()

    ckpt = _load_json(CHECKPOINT, {"files": {}})
    files = sorted(
        [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED],
        key=lambda x: x.name.lower(),
    )
    done_keys = set(ckpt.get("files") or {})
    todo = [f for f in files if str(f.resolve()) not in done_keys or args.reset_checkpoint]
    if args.limit is not None:
        todo = todo[: args.limit]

    logging.info("folder=%s total=%s todo=%s dry_run=%s", folder, len(files), len(todo), args.dry_run)

    prepared = 0
    added = 0
    rejected = 0
    results: list[dict] = []
    pending: list = []

    for f in todo:
        try:
            text = load_text_from_file(f)
        except ValueError as e:
            rejected += 1
            results.append({"file": f.name, "status": "rejected", "note": str(e)[:300]})
            logging.warning("REJECTED %s: %s", f.name, e)
            ckpt.setdefault("files", {})[str(f.resolve())] = {
                "status": "rejected",
                "note": str(e)[:300],
            }
            _save_json(CHECKPOINT, ckpt)
            continue

        q = assess_extracted_text_quality(text)
        if not q["ok"]:
            rejected += 1
            note = ",".join(q["reasons"])
            results.append({"file": f.name, "status": "rejected", "quality": q})
            logging.warning("REJECTED quality %s: %s", f.name, note)
            ckpt.setdefault("files", {})[str(f.resolve())] = {
                "status": "rejected",
                "note": note,
            }
            _save_json(CHECKPOINT, ckpt)
            continue

        docs = chunk_text(text, source=f.name)
        if not docs:
            rejected += 1
            results.append({"file": f.name, "status": "rejected", "note": "chunk_empty"})
            continue

        mapped = map_law_to_domain(law_name=f.stem, source=f.name, text_preview=text[:400])
        domain = mapped["domain"]
        # Fail-fast: only force کیفری when map is unclassified (not when چک→commercial)
        if domain in ("unclassified", "نامشخص", None, ""):
            domain = CRIMINAL_DOMAIN
            forced = True
        else:
            forced = False

        for d in docs:
            meta = d.metadata or {}
            meta["domain"] = domain
            if mapped.get("subdomain"):
                meta["subdomain"] = mapped["subdomain"]
            meta["domain_slug"] = mapped.get("domain_slug") or (
                "criminal" if domain == CRIMINAL_DOMAIN else "unclassified"
            )
            meta["taxonomy_forced"] = "criminal_pilot" if forced else mapped.get("method")
            d.metadata = meta

        prepared += len(docs)
        pending.extend(docs)
        results.append(
            {
                "file": f.name,
                "status": "dry_run_ok" if args.dry_run else "queued",
                "chars": q["chars"],
                "chunks": len(docs),
                "domain": domain,
                "forced_criminal": forced,
                "preview": text[:160].replace("\n", " "),
            }
        )
        logging.info("OK %s chunks=%s domain=%s", f.name, len(docs), domain)
        ckpt.setdefault("files", {})[str(f.resolve())] = {
            "status": "ingested" if not args.dry_run else "dry_run_ok",
            "chunks": len(docs),
        }
        _save_json(CHECKPOINT, ckpt)

    if pending and not args.dry_run:
        added = add_documents(pending, collection_name=args.collection)

    st = None
    if not args.dry_run:
        from app.services.vectorstore import stats as chroma_stats

        st = chroma_stats(args.collection)

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "collection": args.collection,
        "dry_run": args.dry_run,
        "prepared_chunks": prepared,
        "added_chunks": added,
        "rejected_files": rejected,
        "files": results,
        "stats": st,
        "notes": (
            "Pilot: validate encoding before full criminal corpus rescrape. "
            "چک laws in this folder map to commercial — do not force کیفری."
        ),
    }
    _save_json(REPORT, report)
    logging.info("Report %s prepared=%s added=%s rejected=%s", REPORT, prepared, added, rejected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
