"""
Incremental ingest from live scraper outputs into chroma_clean.

Safe to run while scrape_qavanin.py is writing new .docx files:
- waits until file size is stable
- resumes via checkpoint (path + size + mtime)
- uses content_hash dedup inside add_documents
- does NOT auto-delete or wipe chroma_clean

Usage:
  # one pass over current files
  python scripts/ingest_outputs_watch.py --once

  # continuous watch while scraper runs
  python scripts/ingest_outputs_watch.py --watch --poll-seconds 30

  # custom paths
  python scripts/ingest_outputs_watch.py --watch ^
    --folder "D:/.../data-scrapping-law/outputs" ^
    --chroma-dir "D:/.../storage/chroma_clean"
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

DEFAULT_FOLDER = BASE_DIR.parent / "data-scrapping-law" / "outputs"
DEFAULT_CHROMA = BASE_DIR / "storage" / "chroma_clean"
CHECKPOINT = BASE_DIR / "storage" / "outputs_watch_ingest_checkpoint.json"
STATUS = BASE_DIR / "storage" / "outputs_watch_ingest_status.json"


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


def _is_stable(path: Path, wait: float = 1.5) -> bool:
    """True if size/mtime unchanged across a short wait (not mid-write)."""
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
    return prev.get("size") == sig["size"] and prev.get("mtime_ns") == sig["mtime_ns"]


def _mark_done(ckpt: dict, path: Path, *, chunks: int, status: str, note: str = "") -> None:
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


def discover_docx(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.docx") if p.is_file())


def ingest_batch(
    files: list[Path],
    *,
    collection: str,
    batch_size: int,
    ckpt: dict,
) -> dict:
    from app.services.ingestion import chunk_text, load_text_from_file
    from app.services.vectorstore import add_documents, stats

    prepared = 0
    added_total = 0
    rejected = 0
    errors = 0
    pending_docs: list = []
    pending_files: list[tuple[Path, int]] = []

    def flush() -> None:
        nonlocal pending_docs, pending_files, added_total
        if not pending_docs:
            return
        n = add_documents(pending_docs, collection_name=collection)
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

    for f in files:
        if _already_done(ckpt, f):
            continue
        if not _is_stable(f):
            logging.info("Skip unstable (still writing?): %s", f.name)
            continue
        try:
            text = load_text_from_file(f)
            docs = chunk_text(text, source=f.name)
            if not docs:
                rejected += 1
                _mark_done(ckpt, f, chunks=0, status="rejected", note="empty_or_validation")
                _save_json(CHECKPOINT, ckpt)
                logging.warning("Rejected: %s", f.name)
                continue
            pending_docs.extend(docs)
            pending_files.append((f, len(docs)))
            prepared += len(docs)
            logging.info("%s -> %s chunks", f.name, len(docs))
            if len(pending_files) >= batch_size:
                flush()
        except Exception as e:  # noqa: BLE001
            errors += 1
            logging.exception("Failed %s: %s", f, e)
            _mark_done(ckpt, f, chunks=0, status="error", note=str(e)[:200])
            _save_json(CHECKPOINT, ckpt)

    flush()
    st = stats(collection)
    return {
        "prepared_chunks": prepared,
        "added_chunks": added_total,
        "rejected_files": rejected,
        "errors": errors,
        "stats": st,
    }


def run_pass(
    folder: Path,
    *,
    collection: str,
    batch_size: int,
    max_files: int | None,
) -> dict:
    ckpt = _load_json(CHECKPOINT, {"files": {}, "created_at": datetime.now(timezone.utc).isoformat()})
    all_files = discover_docx(folder)
    todo = [f for f in all_files if not _already_done(ckpt, f)]
    if max_files is not None:
        todo = todo[:max_files]

    status = {
        "running": True,
        "folder": str(folder),
        "collection": collection,
        "total_docx": len(all_files),
        "already_done": len(all_files) - len([f for f in all_files if not _already_done(ckpt, f)]),
        "todo_this_pass": len(todo),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json(STATUS, status)
    logging.info(
        "Pass: total=%s todo=%s collection=%s",
        len(all_files),
        len(todo),
        collection,
    )

    summary = ingest_batch(todo, collection=collection, batch_size=batch_size, ckpt=ckpt)
    ckpt = _load_json(CHECKPOINT, ckpt)
    done_n = sum(1 for v in (ckpt.get("files") or {}).values() if v.get("status") == "ingested")
    status.update(
        {
            "running": False,
            "last_pass": summary,
            "checkpoint_ingested_files": done_n,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_json(STATUS, status)
    return {"status": status, "summary": summary}


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Watch/ingest scraper outputs into chroma_clean")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument(
        "--chroma-dir",
        type=Path,
        default=Path(os.environ.get("CHROMA_DB_DIR", str(DEFAULT_CHROMA))),
    )
    parser.add_argument("--collection", default=os.environ.get("CHROMA_COLLECTION", "legal-texts-v2"))
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--watch", action="store_true", help="Poll forever for new files")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--batch-size", type=int, default=20, help="Files per Chroma add flush")
    parser.add_argument("--max-files", type=int, default=None, help="Limit files per pass")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    folder: Path = args.folder
    if not folder.is_absolute():
        folder = (BASE_DIR / folder).resolve()
    if not folder.exists():
        logging.error("Folder not found: %s", folder)
        return 1

    chroma_dir = args.chroma_dir
    if not chroma_dir.is_absolute():
        chroma_dir = (BASE_DIR / chroma_dir).resolve()
    chroma_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CHROMA_DB_DIR"] = str(chroma_dir).replace("\\", "/")
    os.environ["CHROMA_COLLECTION"] = args.collection

    # Import after env is set so config picks up CHROMA_DB_DIR
    from app.services.vectorstore import ensure_embeddings_ready, stats

    ensure_embeddings_ready()
    logging.info("Chroma dir=%s collection=%s stats=%s", chroma_dir, args.collection, stats(args.collection))

    watch = args.watch or not args.once
    if args.once:
        watch = False

    while True:
        try:
            result = run_pass(
                folder,
                collection=args.collection,
                batch_size=args.batch_size,
                max_files=args.max_files,
            )
            logging.info("Pass done: %s", json.dumps(result["summary"], ensure_ascii=False))
        except KeyboardInterrupt:
            logging.info("Interrupted by user")
            st = _load_json(STATUS, {})
            st["running"] = False
            st["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_json(STATUS, st)
            return 0
        except Exception as e:  # noqa: BLE001
            logging.exception("Pass failed: %s", e)

        if not watch:
            break
        logging.info("Sleeping %.1fs before next poll...", args.poll_seconds)
        time.sleep(args.poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
