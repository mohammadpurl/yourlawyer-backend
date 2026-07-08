"""
Fill gaps: ingest only unique chunks missing from ChromaDB.

Scans the full corpus (ignores manifest by default), compares content_hash
against all vectors in Chroma (including legacy rows without metadata hash),
and adds only missing passages.

Usage:
    python scripts/complete_ingest_ghavanin.py --audit-first
    python scripts/complete_ingest_ghavanin.py --batch-files 50
    python scripts/complete_ingest_ghavanin.py --dry-run
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

from langchain_core.documents import Document  # noqa: E402

from app.services.ingestion import chunk_text, load_text_from_file  # noqa: E402
from app.services.vectorstore import (  # noqa: E402
    add_documents,
    ensure_embeddings_ready,
    get_existing_content_hashes,
    stats,
)
from scripts.ghavanin_ingest_utils import (  # noqa: E402
    SOURCE_ROOT,
    compare_corpus_to_chroma,
    iter_source_files,
    save_json_report,
    scan_corpus,
)

REPORT_PATH = BASE_DIR / "storage" / "complete_ingest_report.json"


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    log_path = BASE_DIR / "storage" / "complete_ingest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError as exc:
        print(f"Warning: could not open log file {log_path}: {exc}", file=sys.stderr)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def ingest_file_batch(
    files: list[Path], folder_root: Path
) -> tuple[list[Document], list[str], list[str]]:
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


def run_audit(
    folder: Path, sample: int | None, chroma_hashes: set[str] | None = None
) -> dict:
    if chroma_hashes is None:
        chroma_hashes = get_existing_content_hashes()
    corpus = scan_corpus(folder, max_files=sample)
    return compare_corpus_to_chroma(corpus, chroma_hashes)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Complete ghavanin ingest — add only missing unique chunks"
    )
    parser.add_argument(
        "--folder",
        default=str(SOURCE_ROOT.relative_to(BASE_DIR)),
        help="Corpus folder",
    )
    parser.add_argument(
        "--batch-files",
        type=int,
        default=50,
        help="Number of source files per ingest batch",
    )
    parser.add_argument(
        "--audit-first",
        action="store_true",
        help="Run full corpus audit before ingest and save report",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip pre/post audit (use when resuming a partial run)",
    )
    parser.add_argument(
        "--start-batch",
        type=int,
        default=1,
        metavar="N",
        help="Resume from batch N (1-based; skips earlier file batches)",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Audit only; do not write to ChromaDB",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan corpus and count missing chunks without embedding/writing",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Limit to first N files (testing)",
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

    start_time = time.time()
    existing_hashes = get_existing_content_hashes()
    initial_hash_count = len(existing_hashes)
    initial_stats = stats()
    logging.info(
        "Chroma start: %s vectors, %s unique content hashes",
        initial_stats.get("num_vectors"),
        len(existing_hashes),
    )

    if args.start_batch < 1:
        logging.error("--start-batch must be >= 1")
        return 1

    run_pre_audit = (args.audit_first or args.audit_only or args.dry_run) and not args.no_audit

    if run_pre_audit:
        logging.info("Running corpus audit...")
        audit_summary = run_audit(folder, args.sample, existing_hashes)
        logging.info(
            "Audit: %s%% coverage (%s missing unique chunks of %s)",
            audit_summary["coverage_percent"],
            audit_summary["missing_unique_chunks"],
            audit_summary["corpus_unique_chunks"],
        )
        if args.audit_only:
            save_json_report(
                REPORT_PATH,
                {
                    "mode": "audit_only",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "summary": audit_summary,
                    "chroma_before": initial_stats,
                },
            )
            return 0

    all_files = iter_source_files(folder)
    if args.sample is not None:
        all_files = all_files[: args.sample]

    total_batches = (len(all_files) + args.batch_files - 1) // args.batch_files
    logging.info("Files to process: %s (%s batches of %s)", len(all_files), total_batches, args.batch_files)

    if args.start_batch > total_batches:
        logging.error(
            "--start-batch %s exceeds total batches (%s)",
            args.start_batch,
            total_batches,
        )
        return 1

    if args.start_batch > 1:
        skipped_files = (args.start_batch - 1) * args.batch_files
        logging.info(
            "Resuming from batch %s/%s (skipping first %s files)",
            args.start_batch,
            total_batches,
            skipped_files,
        )

    if args.dry_run:
        logging.info("Dry run — no writes to ChromaDB")
        return 0

    logging.info("Checking embedding model...")
    try:
        ensure_embeddings_ready()
    except Exception as exc:
        logging.error("Embedding model is not ready: %s", exc)
        logging.error("Run: python scripts/download_embedding_model.py")
        return 1

    total_chunks_added = 0
    total_files_processed = 0
    batches_with_additions = 0
    all_failed: list[str] = []
    batch_history: list[dict] = []

    start_file_index = (args.start_batch - 1) * args.batch_files
    for batch_index in range(start_file_index, len(all_files), args.batch_files):
        batch_files = all_files[batch_index : batch_index + args.batch_files]
        batch_num = batch_index // args.batch_files + 1

        logging.info(
            "Batch %s/%s: %s files (known unique hashes: %s)",
            batch_num,
            total_batches,
            len(batch_files),
            len(existing_hashes),
        )

        documents, processed_sources, failed_files = ingest_file_batch(
            batch_files, folder
        )
        all_failed.extend(failed_files)

        added = 0
        if documents:
            try:
                added = add_documents(documents, existing_hashes=existing_hashes)
            except Exception as exc:
                logging.error("Batch %s failed: %s", batch_num, exc)
                return 1

        total_chunks_added += added
        total_files_processed += len(processed_sources)
        if added:
            batches_with_additions += 1

        batch_history.append(
            {
                "batch": batch_num,
                "files": len(processed_sources),
                "chunks_scanned": len(documents),
                "chunks_added": added,
                "failed": len(failed_files),
            }
        )
        logging.info(
            "Batch %s done: scanned=%s added=%s",
            batch_num,
            len(documents),
            added,
        )

    final_stats = stats()
    elapsed = time.time() - start_time

    post_audit = None
    if args.audit_first and not args.no_audit:
        logging.info("Running post-ingest audit...")
        post_audit = run_audit(folder, args.sample, existing_hashes)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "files_processed": total_files_processed,
        "chunks_added": total_chunks_added,
        "batches_with_additions": batches_with_additions,
        "chroma_before": initial_stats,
        "chroma_after": final_stats,
        "unique_hashes_before": initial_hash_count,
        "unique_hashes_after": len(existing_hashes),
        "post_audit": post_audit,
        "failed_files_sample": all_failed[:30],
        "batch_history": batch_history,
    }
    save_json_report(REPORT_PATH, report)

    logging.info("=" * 60)
    logging.info("Complete ingest finished in %.1f seconds", elapsed)
    logging.info("Files processed: %s", total_files_processed)
    logging.info("New chunks added: %s", total_chunks_added)
    logging.info(
        "Chroma vectors: %s -> %s",
        initial_stats.get("num_vectors"),
        final_stats.get("num_vectors"),
    )
    if post_audit:
        logging.info(
            "Final coverage: %s%% (%s missing unique chunks)",
            post_audit["coverage_percent"],
            post_audit["missing_unique_chunks"],
        )
    logging.info("Report: %s", REPORT_PATH)

    return 1 if all_failed and total_files_processed == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
