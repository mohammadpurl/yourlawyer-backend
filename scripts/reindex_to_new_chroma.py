"""
Re-index legal corpus into a NEW ChromaDB directory with current metadata
(ماده / قانون / article_number) — without touching the old vector store.

Why a new DB?
  Old ingest often stored only filename in metadata.source. Citations then
  show file names. Fresh chunking writes law_name + unit_kind + article_number.

Usage (from your-lowyer-back root):

  # 1) Dry-run: count files / sample labels
  python scripts/reindex_to_new_chroma.py --dry-run

  # 2) Full rebuild into a new folder (keeps old chroma intact)
  python scripts/reindex_to_new_chroma.py \\
    --folder data/ghavanin \\
    --chroma-dir storage/chroma_v2 \\
    --batch-files 40

  # 3) After success, point the app at the new DB and restart:
  #    CHROMA_DB_DIR=/app/storage/chroma_v2   (Docker)
  #    or in .env: CHROMA_DB_DIR=.../storage/chroma_v2

  # Optional: only PDF+Word from another folder
  python scripts/reindex_to_new_chroma.py --folder data/uploads --chroma-dir storage/chroma_v2
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

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

WORD_EXTENSIONS = {".docx", ".doc", ".pdf", ".txt"}
EXCLUDED_DIR_NAMES = {"new folder", "uploadwithscript", "__macosx", ".git"}
DEFAULT_SOURCE = BASE_DIR / "data" / "ghavanin"
DEFAULT_CHROMA = BASE_DIR / "storage" / "chroma_v2"
MANIFEST_NAME = "reindex_manifest.json"


def configure_logging(verbose: bool, log_path: Path) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError as exc:
        print(f"Warning: could not open log file: {exc}", file=sys.stderr)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in WORD_EXTENSIONS:
            continue
        if any(part.lower() in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix())


def sample_citation_labels(documents: list, limit: int = 8) -> list[str]:
    from app.services.rag import _citation_label

    labels: list[str] = []
    seen: set[str] = set()
    for doc in documents:
        label = _citation_label(getattr(doc, "metadata", None) or {})
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-index corpus into a fresh ChromaDB with article metadata"
    )
    parser.add_argument(
        "--folder",
        default=str(DEFAULT_SOURCE),
        help="Source folder (absolute or relative to project root)",
    )
    parser.add_argument(
        "--chroma-dir",
        default=str(DEFAULT_CHROMA),
        help="NEW Chroma persist directory (old DB is not modified)",
    )
    parser.add_argument(
        "--collection",
        default="legal-texts",
        help="Chroma collection name (keep legal-texts for app compatibility)",
    )
    parser.add_argument("--batch-files", type=int, default=40)
    parser.add_argument(
        "--skip-processed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume using reindex manifest under the new chroma dir",
    )
    parser.add_argument(
        "--reset-manifest",
        action="store_true",
        help="Ignore previous reindex manifest and process all files again",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_absolute():
        folder = BASE_DIR / folder
    chroma_dir = Path(args.chroma_dir)
    if not chroma_dir.is_absolute():
        chroma_dir = BASE_DIR / chroma_dir

    log_path = chroma_dir / "reindex.log"
    configure_logging(args.verbose, log_path)

    if not folder.exists():
        logging.error("Source folder not found: %s", folder)
        return 1

    # Point vectorstore at the NEW directory before importing app services
    # that read PERSIST_DIRECTORY at call time via config.
    os.environ["CHROMA_DB_DIR"] = chroma_dir.as_posix()

    # Reload config module if already imported (fresh process is fine)
    import importlib

    import app.core.config as config_mod

    importlib.reload(config_mod)
    config_mod.PERSIST_DIRECTORY = chroma_dir.as_posix()

    from app.services.ingestion import chunk_text, load_text_from_file
    from app.services.vectorstore import (
        add_documents,
        ensure_embeddings_ready,
        get_existing_content_hashes,
        stats,
    )

    chroma_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = chroma_dir / MANIFEST_NAME

    if args.reset_manifest and manifest_path.exists():
        manifest_path.unlink()
        logging.info("Removed old reindex manifest")

    if manifest_path.exists() and not args.reset_manifest:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {"processed_sources": [], "history": []}
    else:
        manifest = {"processed_sources": [], "history": []}

    processed_set = set(manifest.get("processed_sources", []))
    all_files = iter_source_files(folder)

    if args.skip_processed and not args.reset_manifest:
        pending = [
            p
            for p in all_files
            if p.relative_to(folder).as_posix() not in processed_set
        ]
    else:
        pending = all_files

    logging.info("Source folder : %s", folder)
    logging.info("New Chroma dir: %s", chroma_dir)
    logging.info("Collection    : %s", args.collection)
    logging.info("Files found   : %s", len(all_files))
    logging.info("Pending       : %s", len(pending))

    if args.dry_run:
        for path in pending[:5]:
            rel = path.relative_to(folder).as_posix()
            try:
                content = load_text_from_file(path)
                docs = chunk_text(content, source=rel)
                labels = sample_citation_labels(docs)
                logging.info("Sample %s → %s chunks; labels=%s", rel, len(docs), labels)
            except Exception as exc:
                logging.error("Dry-run failed for %s: %s", rel, exc)
        logging.info("Dry-run only — no writes.")
        return 0

    if not pending:
        logging.info("Nothing to ingest. Current stats: %s", stats())
        return 0

    logging.info("Loading embedding model...")
    try:
        ensure_embeddings_ready()
    except Exception as exc:
        logging.error("Embedding model not ready: %s", exc)
        logging.error("Run: python scripts/download_embedding_model.py")
        return 1

    existing_hashes = get_existing_content_hashes(args.collection)
    logging.info("Existing hashes in NEW store: %s", len(existing_hashes))

    started = time.time()
    total_chunks = 0
    total_files = 0
    failures: list[str] = []

    for batch_i in range(0, len(pending), args.batch_files):
        batch = pending[batch_i : batch_i + args.batch_files]
        batch_no = batch_i // args.batch_files + 1
        batches = (len(pending) + args.batch_files - 1) // args.batch_files
        logging.info("Batch %s/%s (%s files)", batch_no, batches, len(batch))

        documents = []
        processed_sources: list[str] = []
        for file_path in batch:
            rel = file_path.relative_to(folder).as_posix()
            try:
                content = load_text_from_file(file_path)
                documents.extend(chunk_text(content, source=rel))
                processed_sources.append(rel)
            except Exception as exc:
                msg = f"{rel}: {exc}"
                failures.append(msg)
                logging.error("Failed %s", msg)

        if not documents:
            logging.warning("Batch %s produced no chunks", batch_no)
            continue

        labels = sample_citation_labels(documents)
        logging.info("Sample citation labels: %s", labels)

        try:
            added = add_documents(
                documents,
                collection_name=args.collection,
                existing_hashes=existing_hashes,
            )
        except Exception as exc:
            logging.error("Chroma write failed on batch %s: %s", batch_no, exc)
            logging.error("Fix and re-run; this batch was NOT marked processed.")
            return 1

        total_chunks += added
        total_files += len(processed_sources)
        processed_set.update(processed_sources)
        manifest["processed_sources"] = sorted(processed_set)
        manifest.setdefault("history", []).append(
            {
                "batch": batch_no,
                "files": len(processed_sources),
                "chunks_added": added,
                "sample_labels": labels,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info(
            "Batch %s done: files=%s chunks_added=%s",
            batch_no,
            len(processed_sources),
            added,
        )

    elapsed = time.time() - started
    final = stats()
    logging.info("=" * 60)
    logging.info("Reindex finished in %.1fs", elapsed)
    logging.info("Files processed: %s", total_files)
    logging.info("Chunks added   : %s", total_chunks)
    logging.info("New store size : %s vectors @ %s", final.get("num_vectors"), chroma_dir)
    logging.info(
        "Next step: set CHROMA_DB_DIR=%s and restart the backend.",
        chroma_dir.as_posix(),
    )
    if failures:
        logging.warning("Failures: %s (showing up to 15)", len(failures))
        for row in failures[:15]:
            logging.warning("  %s", row)
        return 1 if total_files == 0 else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
