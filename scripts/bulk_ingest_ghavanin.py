"""
Offline bulk ingest for data/ghavanin without HTTP API.

Processes Word files directly, chunks with legal-aware splitting, deduplicates
via content_hash, and writes to ChromaDB in batches.

Usage:
    python scripts/bulk_ingest_ghavanin.py
    python scripts/bulk_ingest_ghavanin.py --folder data/ghavanin --batch-files 50
    python scripts/bulk_ingest_ghavanin.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.ingestion import chunk_text, load_text_from_file  # noqa: E402
from app.services.vectorstore import (  # noqa: E402
    add_documents,
    ensure_embeddings_ready,
    get_existing_content_hashes,
    stats,
)

SOURCE_ROOT = BASE_DIR / "data" / "ghavanin"
MANIFEST_PATH = BASE_DIR / "storage" / "ingest_manifest.json"
EXCLUDED_DIR_NAMES = {"new folder", "uploadwithscript"}
WORD_EXTENSIONS = {".docx", ".doc"}


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"processed_sources": [], "history": []}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"processed_sources": [], "history": []}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
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


def ingest_file_batch(
    files: list[Path], folder_root: Path
) -> tuple[list, list[str], list[str]]:
    from langchain_core.documents import Document

    documents: list[Document] = []
    processed_sources: list[str] = []
    failed_files: list[str] = []

    for file_path in files:
        relative_source = file_path.relative_to(folder_root).as_posix()
        try:
            content = load_text_from_file(file_path)
            documents.extend(chunk_text(content, source=relative_source))
            processed_sources.append(relative_source)
        except Exception as exc:
            failed_files.append(f"{relative_source}: {exc}")
            logging.error("Failed to process %s: %s", relative_source, exc)

    return documents, processed_sources, failed_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk ingest ghavanin files into ChromaDB")
    parser.add_argument(
        "--folder",
        default=str(SOURCE_ROOT.relative_to(BASE_DIR)),
        help="Folder path relative to project root or absolute path",
    )
    parser.add_argument(
        "--batch-files",
        type=int,
        default=50,
        help="Number of source files per ingest batch",
    )
    parser.add_argument(
        "--skip-processed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip files already listed in ingest manifest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and chunk only; do not write to ChromaDB",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    folder = Path(args.folder)
    if not folder.is_absolute():
        folder = BASE_DIR / folder

    if not folder.exists():
        logging.error("Folder not found: %s", folder)
        return 1

    manifest = load_manifest()
    processed_set = set(manifest.get("processed_sources", []))
    all_files = iter_source_files(folder)

    if args.skip_processed:
        pending_files = [
            path
            for path in all_files
            if path.relative_to(folder).as_posix() not in processed_set
        ]
    else:
        pending_files = all_files

    logging.info("Folder: %s", folder)
    logging.info("Total Word files found: %s", len(all_files))
    logging.info("Pending files: %s", len(pending_files))
    logging.info("Batch size (files): %s", args.batch_files)

    if not pending_files:
        logging.info("Nothing to ingest.")
        current_stats = stats()
        logging.info(
            "Current vector store: %s vectors in %s",
            current_stats.get("num_vectors"),
            current_stats.get("persist_directory"),
        )
        return 0

    if args.dry_run:
        sample = pending_files[: min(5, len(pending_files))]
        logging.info("Dry run sample files:")
        for path in sample:
            logging.info("  - %s", path.relative_to(folder).as_posix())
        return 0

    logging.info("Checking embedding model (download/load if needed)...")
    try:
        ensure_embeddings_ready()
    except Exception as exc:
        logging.error("Embedding model is not ready: %s", exc)
        logging.error(
            "Run this first (with VPN if needed):\n"
            "  python scripts/download_embedding_model.py"
        )
        return 1

    start_time = time.time()
    total_chunks_added = 0
    total_files_processed = 0
    all_failed: list[str] = []
    existing_hashes = get_existing_content_hashes()
    logging.info("Existing chunks in vector store: %s", len(existing_hashes))

    for batch_index in range(0, len(pending_files), args.batch_files):
        batch_files = pending_files[batch_index : batch_index + args.batch_files]
        batch_num = batch_index // args.batch_files + 1
        total_batches = (len(pending_files) + args.batch_files - 1) // args.batch_files

        logging.info(
            "Batch %s/%s: processing %s files",
            batch_num,
            total_batches,
            len(batch_files),
        )

        documents, processed_sources, failed_files = ingest_file_batch(
            batch_files, folder
        )
        all_failed.extend(failed_files)

        if not documents:
            logging.warning("Batch %s produced no documents", batch_num)
            continue

        try:
            added = add_documents(documents, existing_hashes=existing_hashes)
        except Exception as exc:
            logging.error("Batch %s failed while writing to ChromaDB: %s", batch_num, exc)
            logging.error("Fix the issue and rerun; this batch was not marked as processed.")
            return 1

        total_chunks_added += added
        total_files_processed += len(processed_sources)

        processed_set.update(processed_sources)
        manifest["processed_sources"] = sorted(processed_set)
        manifest.setdefault("history", []).append(
            {
                "batch": batch_num,
                "files_processed": len(processed_sources),
                "chunks_added": added,
                "failed_files": failed_files,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        save_manifest(manifest)

        logging.info(
            "Batch %s done: files=%s chunks_added=%s",
            batch_num,
            len(processed_sources),
            added,
        )

    elapsed = time.time() - start_time
    final_stats = stats()

    logging.info("=" * 60)
    logging.info("Bulk ingest completed in %.1f seconds", elapsed)
    logging.info("Files processed: %s", total_files_processed)
    logging.info("Chunks added: %s", total_chunks_added)
    logging.info(
        "Vector store total: %s vectors",
        final_stats.get("num_vectors"),
    )
    if all_failed:
        logging.warning("Failed files (%s):", len(all_failed))
        for failure in all_failed[:10]:
            logging.warning("  %s", failure)

    return 1 if all_failed and total_files_processed == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
