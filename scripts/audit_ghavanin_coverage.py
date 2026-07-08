"""
Compare unique legal chunks in data/ghavanin against ChromaDB.

Does NOT load the embedding model — only scans files and reads Chroma metadata.

Usage:
    python scripts/audit_ghavanin_coverage.py
    python scripts/audit_ghavanin_coverage.py --sample 200
    python scripts/audit_ghavanin_coverage.py --output storage/audit_report.json
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.vectorstore import get_existing_content_hashes, stats  # noqa: E402
from scripts.ghavanin_ingest_utils import (  # noqa: E402
    SOURCE_ROOT,
    compare_corpus_to_chroma,
    save_json_report,
    scan_corpus,
)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit ghavanin corpus coverage in ChromaDB"
    )
    parser.add_argument(
        "--folder",
        default=str(SOURCE_ROOT.relative_to(BASE_DIR)),
        help="Corpus folder (relative to project root or absolute)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Scan only the first N files (for quick checks)",
    )
    parser.add_argument(
        "--output",
        default=str(BASE_DIR / "storage" / "audit_report.json"),
        help="Where to write the JSON report",
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

    start = time.time()
    logging.info("Loading content hashes from ChromaDB...")
    chroma_hashes = get_existing_content_hashes()
    chroma_stats = stats()
    logging.info(
        "Chroma: %s vectors, %s unique content hashes",
        chroma_stats.get("num_vectors"),
        len(chroma_hashes),
    )

    logging.info("Scanning corpus at %s ...", folder)
    corpus = scan_corpus(folder, max_files=args.sample)
    comparison = compare_corpus_to_chroma(corpus, chroma_hashes)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "chroma": chroma_stats,
        "summary": comparison,
        "failed_files_sample": corpus.failed_files[:20],
    }

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    save_json_report(output_path, report)

    elapsed = time.time() - start
    logging.info("=" * 60)
    logging.info("Audit completed in %.1f seconds", elapsed)
    logging.info("Corpus files scanned: %s", comparison["corpus_total_files"])
    logging.info("Corpus unique chunks: %s", comparison["corpus_unique_chunks"])
    logging.info("Chroma unique hashes: %s", comparison["chroma_unique_hashes"])
    logging.info(
        "Coverage: %s%% (%s / %s unique chunks in Chroma)",
        comparison["coverage_percent"],
        comparison["covered_unique_chunks"],
        comparison["corpus_unique_chunks"],
    )
    logging.info("Missing unique chunks: %s", comparison["missing_unique_chunks"])
    logging.info(
        "Files: fully=%s partial=%s none=%s failed=%s",
        comparison["files_fully_covered"],
        comparison["files_partially_covered"],
        comparison["files_not_covered"],
        comparison["corpus_failed_files"],
    )
    logging.info("Report saved to %s", output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
