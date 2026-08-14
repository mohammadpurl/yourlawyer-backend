"""
Ingest workplace-safety آیین‌نامه PDFs from data/Aein name into Chroma.

Uses the same chunk_text / add_documents pipeline as priority ingest, with:
- recursive PDF/DOCX/TXT discovery
- checkpoint resume (path + size + mtime)
- forced taxonomy tags for ایمنی_و_حفاظت_فنی when heuristic is weak

Usage:
  python scripts/ingest_aein_name_safety.py --dry-run --limit 5
  python scripts/ingest_aein_name_safety.py
  python scripts/ingest_aein_name_safety.py --folder "data/Aein name" --collection legal-texts-v2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_FOLDER = BASE_DIR / "data" / "Aein name"
DEFAULT_CHROMA = BASE_DIR / "storage" / "chroma_clean"
CHECKPOINT = BASE_DIR / "storage" / "aein_name_ingest_checkpoint.json"
REPORT = BASE_DIR / "storage" / "aein_name_ingest_report.json"

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md"}

SAFETY_DOMAIN = "کار_و_تامین_اجتماعی"
SAFETY_SUBDOMAIN = "ایمنی_و_حفاظت_فنی"


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


def _file_signature(path: Path) -> dict:
    st = path.stat()
    return {
        "size": st.st_size,
        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
    }


def _is_stable(path: Path, wait: float = 0.8) -> bool:
    try:
        a = _file_signature(path)
        time.sleep(wait)
        b = _file_signature(path)
        return a == b and a["size"] > 0
    except OSError:
        return False


def _already_done(ckpt: dict, path: Path) -> bool:
    key = str(path.resolve())
    prev = (ckpt.get("files") or {}).get(key)
    if not prev:
        return False
    try:
        sig = _file_signature(path)
    except OSError:
        return False
    return (
        prev.get("size") == sig["size"]
        and prev.get("mtime_ns") == sig["mtime_ns"]
        and prev.get("status") in {"ingested", "rejected"}
    )


def _mark_done(
    ckpt: dict,
    path: Path,
    *,
    chunks: int,
    status: str,
    note: str = "",
) -> None:
    key = str(path.resolve())
    sig = _file_signature(path)
    ckpt.setdefault("files", {})[key] = {
        **sig,
        "at": datetime.now(timezone.utc).isoformat(),
        "chunks": chunks,
        "status": status,
        "note": note,
        "name": path.name,
    }
    ckpt["updated_at"] = datetime.now(timezone.utc).isoformat()


def discover_files(folder: Path) -> list[Path]:
    files: list[Path] = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(p)
    return sorted(files, key=lambda x: x.name.lower())


def _apply_safety_taxonomy(docs: list) -> None:
    """Strengthen domain/subdomain for this safety-regulation folder."""
    for doc in docs:
        meta = getattr(doc, "metadata", None) or {}
        domain = str(meta.get("domain") or "")
        subdomain = meta.get("subdomain")
        weak = (
            not domain
            or domain == "نامشخص"
            or domain != SAFETY_DOMAIN
            or not subdomain
        )
        if weak:
            meta["domain"] = SAFETY_DOMAIN
            meta["subdomain"] = SAFETY_SUBDOMAIN
            meta["taxonomy_forced"] = "aein_name_safety"
            doc.metadata = meta


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Ingest Aein name safety آیین‌نامه PDFs into Chroma"
    )
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
    parser.add_argument("--limit", type=int, default=None, help="Max files this run")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Files per Chroma add flush",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract + chunk only; do not write Chroma",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Ignore previous checkpoint and reprocess files",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    folder: Path = args.folder
    if not folder.is_absolute():
        folder = (BASE_DIR / folder).resolve()
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

    from app.services.ingestion import chunk_text, load_text_from_file

    if not args.dry_run:
        from app.services.vectorstore import (
            add_documents,
            ensure_embeddings_ready,
            stats,
        )

        ensure_embeddings_ready()
        logging.info(
            "Chroma dir=%s collection=%s stats=%s",
            chroma_dir,
            args.collection,
            stats(args.collection),
        )

    if args.reset_checkpoint and CHECKPOINT.exists():
        CHECKPOINT.unlink()
        logging.info("Checkpoint cleared")

    ckpt = _load_json(
        CHECKPOINT,
        {"files": {}, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    all_files = discover_files(folder)
    todo = [f for f in all_files if args.reset_checkpoint or not _already_done(ckpt, f)]
    if args.limit is not None:
        todo = todo[: args.limit]

    logging.info(
        "Folder=%s total=%s todo=%s dry_run=%s collection=%s",
        folder,
        len(all_files),
        len(todo),
        args.dry_run,
        args.collection,
    )

    prepared = 0
    added_total = 0
    rejected = 0
    empty_text = 0
    errors = 0
    pending_docs: list = []
    pending_files: list[tuple[Path, int]] = []
    file_results: list[dict] = []

    def flush() -> None:
        nonlocal pending_docs, pending_files, added_total
        if args.dry_run or not pending_docs:
            pending_docs = []
            pending_files = []
            return
        n = add_documents(pending_docs, collection_name=args.collection)
        added_total += n
        for f, n_chunks in pending_files:
            _mark_done(ckpt, f, chunks=n_chunks, status="ingested")
        _save_json(CHECKPOINT, ckpt)
        logging.info(
            "Flushed batch: files=%s chunks_sent=%s added=%s",
            len(pending_files),
            len(pending_docs),
            n,
        )
        pending_docs = []
        pending_files = []

    for f in todo:
        if not _is_stable(f):
            logging.info("Skip unstable: %s", f.name)
            continue
        try:
            text = load_text_from_file(f)
            text_len = len((text or "").strip())
            if text_len < 40:
                empty_text += 1
                rejected += 1
                status = "rejected"
                note = "empty_or_scan_pdf"
                if args.dry_run:
                    status = "dry_run_ok"
                    note = "empty_text_preview"
                _mark_done(ckpt, f, chunks=0, status=status, note=note)
                _save_json(CHECKPOINT, ckpt)
                file_results.append(
                    {
                        "file": f.name,
                        "chars": text_len,
                        "chunks": 0,
                        "status": note,
                    }
                )
                logging.warning("Empty/scan PDF?: %s (chars=%s)", f.name, text_len)
                continue

            docs = chunk_text(text, source=f.name)
            if not docs:
                rejected += 1
                _mark_done(
                    ckpt,
                    f,
                    chunks=0,
                    status="rejected" if not args.dry_run else "dry_run_ok",
                    note="empty_or_validation",
                )
                _save_json(CHECKPOINT, ckpt)
                file_results.append(
                    {
                        "file": f.name,
                        "chars": text_len,
                        "chunks": 0,
                        "status": "rejected",
                    }
                )
                logging.warning("Rejected after chunk: %s", f.name)
                continue

            _apply_safety_taxonomy(docs)
            prepared += len(docs)
            logging.info("%s -> %s chunks (chars=%s)", f.name, len(docs), text_len)
            file_results.append(
                {
                    "file": f.name,
                    "chars": text_len,
                    "chunks": len(docs),
                    "status": "dry_run" if args.dry_run else "queued",
                    "domain": docs[0].metadata.get("domain"),
                    "subdomain": docs[0].metadata.get("subdomain"),
                }
            )

            if args.dry_run:
                _mark_done(ckpt, f, chunks=len(docs), status="dry_run_ok")
                _save_json(CHECKPOINT, ckpt)
                continue

            pending_docs.extend(docs)
            pending_files.append((f, len(docs)))
            if len(pending_files) >= args.batch_size:
                flush()
        except Exception as e:  # noqa: BLE001
            errors += 1
            logging.exception("Failed %s: %s", f, e)
            _mark_done(ckpt, f, chunks=0, status="error", note=str(e)[:200])
            _save_json(CHECKPOINT, ckpt)
            file_results.append(
                {"file": f.name, "chunks": 0, "status": "error", "error": str(e)[:200]}
            )

    flush()

    st = None
    if not args.dry_run:
        from app.services.vectorstore import stats

        st = stats(args.collection)

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "collection": args.collection,
        "chroma_dir": str(chroma_dir),
        "dry_run": args.dry_run,
        "total_files_in_folder": len(all_files),
        "todo_this_run": len(todo),
        "prepared_chunks": prepared,
        "added_chunks": added_total,
        "rejected_files": rejected,
        "empty_text_files": empty_text,
        "errors": errors,
        "stats": st,
        "files": file_results,
        "note": (
            "After successful ingest, sync chroma to server if needed. "
            "Re-enable ENABLE_DOMAIN_FILTERED_RETRIEVAL only after broader retag."
        ),
    }
    _save_json(REPORT, report)
    logging.info("Report written: %s", REPORT)
    logging.info(
        "Done: prepared=%s added=%s rejected=%s empty_text=%s errors=%s",
        prepared,
        added_total,
        rejected,
        empty_text,
        errors,
    )
    return 1 if errors and not args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
