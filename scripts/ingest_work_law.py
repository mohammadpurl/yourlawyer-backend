"""
Ingest work / social-security PDFs from data/work-law into Chroma — safely.

Avoids the Aein-name hard-labor failure mode:
  - pypdf dumping ``/u0631/...`` glyph escapes into Chroma
  - scan-only PDFs (0 extractable chars) still getting queued

Pipeline:
  1. PyMuPDF-first extract + NFKC normalize (see ``app.services.ingestion._load_pdf``)
  2. Quality gate rejects empty/scan/garbled text
  3. Forced taxonomy: کار_و_تامین_اجتماعی
  4. Clean Persian ``source`` / law_name overrides for citations

Usage:
  python scripts/ingest_work_law.py --dry-run
  python scripts/ingest_work_law.py
  python scripts/ingest_work_law.py --files "قانون کار.pdf"   # will reject if scan
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

DEFAULT_FOLDER = BASE_DIR / "data" / "work-law"
DEFAULT_CHROMA = BASE_DIR / "storage" / "chroma_clean"
CHECKPOINT = BASE_DIR / "storage" / "work_law_ingest_checkpoint.json"
REPORT = BASE_DIR / "storage" / "work_law_ingest_report.json"

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md"}

LABOR_DOMAIN = "کار_و_تامین_اجتماعی"

# Map ugly download names → citation-friendly source filenames
SOURCE_OVERRIDES: dict[str, str] = {
    "tamin-law_TecKhU3.pdf": "قانون تأمین اجتماعی.pdf",
    "workaff-laws-14884.pdf": "قانون کار.pdf",
}

# Optional subdomain hints by clean source stem
SUBDOMAIN_HINTS: dict[str, str] = {
    "قانون تأمین اجتماعی": "بیمه_و_تامین_اجتماعی",
    "قانون تامین اجتماعی": "بیمه_و_تامین_اجتماعی",
    "قانون کار": "روابط_کار",
}


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


def _is_stable(path: Path, wait: float = 0.5) -> bool:
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


def discover_files(folder: Path, only_names: set[str] | None) -> list[Path]:
    files: list[Path] = []
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if only_names and p.name not in only_names:
            continue
        files.append(p)
    return sorted(files, key=lambda x: x.name.lower())


def _citation_source(path: Path) -> str:
    return SOURCE_OVERRIDES.get(path.name, path.name)


def _apply_labor_taxonomy(docs: list, citation_source: str) -> None:
    stem = Path(citation_source).stem
    subdomain = None
    for key, sub in SUBDOMAIN_HINTS.items():
        if key in stem:
            subdomain = sub
            break
    for doc in docs:
        meta = getattr(doc, "metadata", None) or {}
        meta["domain"] = LABOR_DOMAIN
        if subdomain:
            meta["subdomain"] = subdomain
        meta["taxonomy_forced"] = "work_law_ingest"
        meta["law_name"] = stem
        meta["source"] = citation_source
        doc.metadata = meta


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Safely ingest data/work-law PDFs into Chroma"
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
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Optional basename filter, e.g. tamin-law_TecKhU3.pdf",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-checkpoint", action="store_true")
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

    from app.services.ingestion import (
        assess_extracted_text_quality,
        chunk_text,
        load_text_from_file,
    )

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
    only = set(args.files) if args.files else None
    all_files = discover_files(folder, only)
    todo = [f for f in all_files if args.reset_checkpoint or not _already_done(ckpt, f)]
    if args.limit is not None:
        todo = todo[: args.limit]

    logging.info(
        "Folder=%s total=%s todo=%s dry_run=%s",
        folder,
        len(all_files),
        len(todo),
        args.dry_run,
    )

    prepared = 0
    added_total = 0
    rejected = 0
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
            "Flushed: files=%s chunks_sent=%s added=%s",
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
        citation = _citation_source(f)
        try:
            text = load_text_from_file(f)
        except ValueError as e:
            rejected += 1
            note = str(e)
            _mark_done(
                ckpt,
                f,
                chunks=0,
                status="rejected" if not args.dry_run else "dry_run_rejected",
                note=note[:500],
            )
            _save_json(CHECKPOINT, ckpt)
            file_results.append(
                {
                    "file": f.name,
                    "citation_source": citation,
                    "chars": 0,
                    "chunks": 0,
                    "status": "rejected",
                    "note": note[:300],
                }
            )
            logging.warning("REJECTED %s — %s", f.name, note)
            continue
        except Exception as e:
            errors += 1
            logging.exception("Error reading %s: %s", f.name, e)
            continue

        quality = assess_extracted_text_quality(text)
        text_len = quality["chars"]
        preview = (text or "").strip()[:220].replace("\n", " ")

        if not quality["ok"]:
            rejected += 1
            note = "quality:" + ",".join(quality["reasons"])
            _mark_done(
                ckpt,
                f,
                chunks=0,
                status="rejected" if not args.dry_run else "dry_run_rejected",
                note=note,
            )
            _save_json(CHECKPOINT, ckpt)
            file_results.append(
                {
                    "file": f.name,
                    "citation_source": citation,
                    "chars": text_len,
                    "chunks": 0,
                    "status": "rejected",
                    "quality": quality,
                    "preview": preview,
                }
            )
            logging.warning("REJECTED quality %s — %s", f.name, note)
            continue

        docs = chunk_text(text, source=citation)
        if not docs:
            rejected += 1
            _mark_done(
                ckpt,
                f,
                chunks=0,
                status="rejected" if not args.dry_run else "dry_run_rejected",
                note="empty_or_validation",
            )
            _save_json(CHECKPOINT, ckpt)
            file_results.append(
                {
                    "file": f.name,
                    "citation_source": citation,
                    "chars": text_len,
                    "chunks": 0,
                    "status": "rejected",
                    "note": "chunk/validation empty",
                    "preview": preview,
                }
            )
            logging.warning("Rejected after chunk: %s", f.name)
            continue

        _apply_labor_taxonomy(docs, citation)
        prepared += len(docs)
        pending_docs.extend(docs)
        pending_files.append((f, len(docs)))
        file_results.append(
            {
                "file": f.name,
                "citation_source": citation,
                "chars": text_len,
                "persian_letters": quality["persian_letters"],
                "chunks": len(docs),
                "status": "dry_run_ok" if args.dry_run else "queued",
                "domain": LABOR_DOMAIN,
                "preview": preview,
            }
        )
        logging.info(
            "OK %s → citation=%s chars=%s chunks=%s preview=%s",
            f.name,
            citation,
            text_len,
            len(docs),
            preview[:80],
        )

        if len(pending_files) >= 3:
            flush()

    flush()

    st = None
    if not args.dry_run:
        from app.services.vectorstore import stats as chroma_stats

        st = chroma_stats(args.collection)

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "collection": args.collection,
        "chroma_dir": str(chroma_dir),
        "dry_run": args.dry_run,
        "total_files": len(all_files),
        "todo": len(todo),
        "prepared_chunks": prepared,
        "added_chunks": added_total,
        "rejected_files": rejected,
        "errors": errors,
        "stats": st,
        "files": file_results,
        "notes": (
            "قانون کار.pdf is often a scan (0 text). Prefer workaff-laws-14884.pdf "
            "which extracts cleanly as قانون کار. "
            "Aein-name hard-labor junk was caused by pypdf /uXXXX dumps — "
            "loader now prefers pymupdf + quality gate."
        ),
    }
    _save_json(REPORT, report)
    logging.info("Report written: %s", REPORT)
    logging.info(
        "Summary prepared=%s added=%s rejected=%s errors=%s",
        prepared,
        added_total,
        rejected,
        errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
