"""Shared helpers for ghavanin corpus scan, audit, and ingest scripts."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document

from app.services.ingestion import chunk_text, hash_page_content, load_text_from_file

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_ROOT = BASE_DIR / "data" / "ghavanin"
EXCLUDED_DIR_NAMES = {"new folder", "uploadwithscript"}
WORD_EXTENSIONS = {".docx", ".doc"}
FILE_TIMEOUT_SECONDS = 120


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


def chunk_file(
    file_path: Path,
    folder_root: Path,
    *,
    timeout_seconds: int = FILE_TIMEOUT_SECONDS,
) -> tuple[str, list[Document], str | None]:
    """Return (relative_source, documents, error)."""
    relative_source = file_path.relative_to(folder_root).as_posix()

    def _process() -> tuple[list[Document], str | None]:
        try:
            content = load_text_from_file(file_path)
            return chunk_text(content, source=relative_source), None
        except Exception as exc:
            return [], str(exc)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_process)
        try:
            documents, error = future.result(timeout=timeout_seconds)
            return relative_source, documents, error
        except FuturesTimeoutError:
            return relative_source, [], f"timeout after {timeout_seconds}s"


@dataclass
class CorpusScanResult:
    total_files: int = 0
    failed_files: list[str] = field(default_factory=list)
    total_chunks: int = 0
    unique_hashes: set[str] = field(default_factory=set)
    hash_to_sources: dict[str, set[str]] = field(default_factory=dict)
    file_chunk_counts: dict[str, int] = field(default_factory=dict)
    file_unique_counts: dict[str, int] = field(default_factory=dict)

    def register_file(
        self,
        source: str,
        documents: list[Document],
        error: str | None,
    ) -> None:
        self.total_files += 1
        if error:
            self.failed_files.append(f"{source}: {error}")
            return

        file_hashes: set[str] = set()
        for doc in documents:
            content_hash = doc.metadata.get("content_hash") or hash_page_content(
                doc.page_content
            )
            self.unique_hashes.add(content_hash)
            self.hash_to_sources.setdefault(content_hash, set()).add(source)
            file_hashes.add(content_hash)

        self.total_chunks += len(documents)
        self.file_chunk_counts[source] = len(documents)
        self.file_unique_counts[source] = len(file_hashes)


def scan_corpus(
    folder: Path,
    *,
    max_files: int | None = None,
    progress_every: int = 100,
) -> CorpusScanResult:
    """Scan all Word files and collect chunk hashes without touching ChromaDB."""
    result = CorpusScanResult()
    files = iter_source_files(folder)
    if max_files is not None:
        files = files[:max_files]

    logging.info("Scanning %s Word files in %s", len(files), folder)

    for index, file_path in enumerate(files, start=1):
        source, documents, error = chunk_file(file_path, folder)
        result.register_file(source, documents, error)

        if error:
            logging.warning("File failed (%s): %s", source, error)

        if progress_every and index % progress_every == 0:
            logging.info(
                "Scanned %s/%s files | unique chunks: %s | last: %s",
                index,
                len(files),
                len(result.unique_hashes),
                source,
            )

    logging.info(
        "Scan done: %s files, %s unique chunks, %s failed",
        result.total_files,
        len(result.unique_hashes),
        len(result.failed_files),
    )
    return result


def compare_corpus_to_chroma(
    corpus: CorpusScanResult, chroma_hashes: set[str]
) -> dict:
    missing_hashes = corpus.unique_hashes - chroma_hashes
    extra_hashes = chroma_hashes - corpus.unique_hashes

    files_fully_covered = 0
    files_partially_covered = 0
    files_not_covered = 0
    files_with_missing: list[dict] = []

    for source, chunk_count in corpus.file_chunk_counts.items():
        if chunk_count == 0:
            continue

        file_hashes = {
            h
            for h, sources in corpus.hash_to_sources.items()
            if source in sources
        }
        covered = file_hashes & chroma_hashes
        missing_count = len(file_hashes - chroma_hashes)

        if missing_count == 0:
            files_fully_covered += 1
        elif covered:
            files_partially_covered += 1
            files_with_missing.append(
                {
                    "source": source,
                    "unique_chunks": len(file_hashes),
                    "missing_unique_chunks": missing_count,
                }
            )
        else:
            files_not_covered += 1
            files_with_missing.append(
                {
                    "source": source,
                    "unique_chunks": len(file_hashes),
                    "missing_unique_chunks": missing_count,
                }
            )

    files_with_missing.sort(key=lambda item: item["missing_unique_chunks"], reverse=True)

    unique_in_corpus = len(corpus.unique_hashes)
    covered_unique = len(corpus.unique_hashes & chroma_hashes)
    coverage_pct = (
        round(100.0 * covered_unique / unique_in_corpus, 2)
        if unique_in_corpus
        else 100.0
    )

    return {
        "corpus_total_files": corpus.total_files,
        "corpus_failed_files": len(corpus.failed_files),
        "corpus_total_chunks": corpus.total_chunks,
        "corpus_unique_chunks": unique_in_corpus,
        "chroma_unique_hashes": len(chroma_hashes),
        "covered_unique_chunks": covered_unique,
        "missing_unique_chunks": len(missing_hashes),
        "coverage_percent": coverage_pct,
        "extra_in_chroma_not_in_corpus": len(extra_hashes),
        "files_fully_covered": files_fully_covered,
        "files_partially_covered": files_partially_covered,
        "files_not_covered": files_not_covered,
        "top_files_with_missing": files_with_missing[:50],
    }


def save_json_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
