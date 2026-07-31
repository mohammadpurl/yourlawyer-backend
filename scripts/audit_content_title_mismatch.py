"""
Audit Chroma sources for title/content mismatch (cross-contamination).

Detects sources whose filename/title claims one law but chunk text looks like
another (especially «برنامه هفتم» mislabelled as unrelated laws).

Usage:
    python scripts/audit_content_title_mismatch.py
    python scripts/audit_content_title_mismatch.py --chroma-dir storage/chroma
    python scripts/audit_content_title_mismatch.py --samples-per-source 5
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# Shared with ingestion validation gate — keep in sync with app/services/content_validation.py
EXPECTED_KEYWORDS: dict[str, list[str]] = {
    "قانون مدنی": ["نکاح", "طلاق", "مهر", "ماده 1133", "ماده ۱۱۳۳", "عقد"],
    "قانون مدني": ["نکاح", "طلاق", "مهر", "ماده 1133", "ماده ۱۱۳۳", "عقد"],
    "قانون حمایت خانواده": [
        "دادگاه خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
        "حضانت",
    ],
    "قانون حمايت خانواده": [
        "دادگاه خانواده",
        "گواهی عدم امکان سازش",
        "طلاق توافقی",
        "طلاق توافقي",
        "حضانت",
    ],
    "آیین دادرسی مدنی": ["دادگاه", "خواهان", "خوانده", "دادخواست"],
    "آيين دادرسي مدني": ["دادگاه", "خواهان", "خوانده", "دادخواست"],
    "آئين دادرسي مدني": ["دادگاه", "خواهان", "خوانده", "دادخواست"],
    "محکومیت های مالی": ["محکوم", "دین", "اعسار", "حبس"],
    "محكوميت هاي مالي": ["محکوم", "دین", "اعسار", "حبس"],
    "اجرای احکام مدنی": ["محکوم‌علیه", "محکوم عليه", "اجرائیه", "اجرائيه", "دادورز"],
    "اجراي احكام مدني": ["محکوم‌علیه", "محکوم عليه", "اجرائیه", "اجرائيه", "دادورز"],
    "قانون کار": ["کارگر", "کارفرما", "قرارداد کار"],
    "قانون كار": ["کارگر", "کارفرما", "قرارداد کار"],
    "قانون مجازات": ["مجازات", "حبس", "جزای نقدی", "جزاي نقدي"],
    "قانون تجارت": ["تاجر", "برات", "شرکت", "شركت"],
}

CONTAMINATION_MARKERS = [
    "برنامه هفتم",
    "برنامه پنجساله هفتم",
    "برنامه پيشرفت",
    "برنامه پیشرفت",
    "پيشرفت جمهوري اسلامي",
    "پیشرفت جمهوری اسلامی",
]


def _norm(text: str) -> str:
    return (
        (text or "")
        .replace("\u200c", " ")
        .replace("ي", "ی")
        .replace("ك", "ک")
    )


def match_expected_title(source: str) -> tuple[str, list[str]] | None:
    """If source filename matches a known law title key, return (key, keywords)."""
    blob = _norm(source)
    # Prefer longer keys first
    for key in sorted(EXPECTED_KEYWORDS.keys(), key=len, reverse=True):
        if _norm(key) in blob:
            return key, EXPECTED_KEYWORDS[key]
    return None


def text_has_any(text: str, needles: list[str]) -> list[str]:
    n = _norm(text)
    return [x for x in needles if _norm(x) in n]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Chroma for title/content mismatches"
    )
    parser.add_argument(
        "--chroma-dir",
        default=str(BASE_DIR / "storage" / "chroma"),
        help="Chroma persist directory",
    )
    parser.add_argument(
        "--samples-per-source",
        type=int,
        default=5,
        help="Max sample chunks stored per suspicious source",
    )
    parser.add_argument(
        "--output",
        default=str(BASE_DIR / "storage" / "content_title_mismatch_report.json"),
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    chroma_dir = Path(args.chroma_dir)
    if not chroma_dir.is_absolute():
        chroma_dir = BASE_DIR / chroma_dir

    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    col = client.get_collection("legal-texts")
    total = col.count()

    # Collect all chunks grouped by source (streaming)
    by_source_docs: dict[str, list[str]] = defaultdict(list)
    by_source_count: Counter[str] = Counter()
    contamination_chunk_count = 0
    batch = 3000
    scanned = 0
    while scanned < total:
        got = col.get(
            limit=min(batch, total - scanned),
            offset=scanned,
            include=["documents", "metadatas"],
        )
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
        for doc, meta in zip(docs, metas):
            src = str((meta or {}).get("source") or "(empty)")
            text = doc or ""
            by_source_count[src] += 1
            # keep up to 20 candidates to sample from later
            if len(by_source_docs[src]) < 20:
                by_source_docs[src].append(text)
            if text_has_any(text, CONTAMINATION_MARKERS):
                contamination_chunk_count += 1
        scanned += len(docs)
        if scanned % 15000 == 0 or scanned >= total:
            print(f"scanned {scanned}/{total}", flush=True)

    # Second pass needed for accurate contamination % if we only counted while
    # scanning — we already counted all chunks above. Good.

    suspicious: list[dict] = []
    title_mismatch: list[dict] = []
    clean_known: list[dict] = []
    unknown_sources: list[dict] = []

    for src, count in sorted(by_source_count.items(), key=lambda x: -x[1]):
        samples_pool = by_source_docs.get(src) or []
        sample_n = min(args.samples_per_source, len(samples_pool))
        samples = random.sample(samples_pool, sample_n) if sample_n else []
        joined = "\n".join(samples)
        markers_found = text_has_any(joined, CONTAMINATION_MARKERS)
        # Also check all kept docs for markers (stronger)
        all_kept = "\n".join(samples_pool)
        markers_in_kept = text_has_any(all_kept, CONTAMINATION_MARKERS) or markers_found

        expected = match_expected_title(src)
        entry_base = {
            "source": src,
            "chunk_count": count,
            "contamination_markers_in_samples": markers_in_kept,
            "sample_snippets": [
                (s[:220].replace("\n", " ").strip()) for s in samples[:3]
            ],
        }

        if expected:
            key, keywords = expected
            hits = text_has_any(joined, keywords)
            # If title is برنامه هفتم itself, contamination markers are OK
            is_barnameh_title = "برنامه هفتم" in _norm(src) or "برنامه پنجساله هفتم" in _norm(
                src
            )
            if markers_in_kept and not is_barnameh_title:
                item = {
                    **entry_base,
                    "matched_title_key": key,
                    "expected_keywords": keywords,
                    "expected_keywords_found": hits,
                    "flag": "cross_contamination_barnameh_haftom",
                }
                suspicious.append(item)
            elif not hits and not is_barnameh_title:
                item = {
                    **entry_base,
                    "matched_title_key": key,
                    "expected_keywords": keywords,
                    "expected_keywords_found": hits,
                    "flag": "title_keyword_mismatch",
                }
                title_mismatch.append(item)
            else:
                clean_known.append(
                    {
                        "source": src,
                        "chunk_count": count,
                        "matched_title_key": key,
                        "expected_keywords_found": hits,
                    }
                )
        else:
            if markers_in_kept and "برنامه هفتم" not in _norm(src):
                # Unknown title but body looks like برنامه هفتم
                suspicious.append(
                    {
                        **entry_base,
                        "matched_title_key": None,
                        "flag": "cross_contamination_barnameh_haftom",
                    }
                )
            else:
                unknown_sources.append(
                    {"source": src, "chunk_count": count, "has_barnameh_markers": bool(markers_in_kept)}
                )

    suspicious_chunk_total = sum(x["chunk_count"] for x in suspicious)
    mismatch_chunk_total = sum(x["chunk_count"] for x in title_mismatch)
    contaminated_or_mismatch_chunks = suspicious_chunk_total  # primary metric

    # More precise: recount contamination across ALL chunks already done
    pct_contamination_markers = (
        round(100.0 * contamination_chunk_count / total, 2) if total else 0.0
    )
    pct_suspicious_sources_chunks = (
        round(100.0 * suspicious_chunk_total / total, 2) if total else 0.0
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chroma_dir": str(chroma_dir),
        "collection": "legal-texts",
        "total_chunks": total,
        "unique_sources": len(by_source_count),
        "summary": {
            "chunks_containing_barnameh_haftom_markers": contamination_chunk_count,
            "percent_chunks_with_barnameh_markers": pct_contamination_markers,
            "suspicious_cross_contamination_sources": len(suspicious),
            "suspicious_cross_contamination_chunks": suspicious_chunk_total,
            "percent_chunks_in_suspicious_sources": pct_suspicious_sources_chunks,
            "title_keyword_mismatch_sources": len(title_mismatch),
            "title_keyword_mismatch_chunks": mismatch_chunk_total,
            "known_title_clean_sources": len(clean_known),
            "unknown_title_sources": len(unknown_sources),
        },
        "suspicious_sources": suspicious,
        "title_keyword_mismatches": title_mismatch,
        "clean_known_sources": clean_known,
        "unknown_sources_sample": unknown_sources[:40],
        "expected_keywords_keys": list(EXPECTED_KEYWORDS.keys()),
        "contamination_markers": CONTAMINATION_MARKERS,
    }

    out = Path(args.output)
    if not out.is_absolute():
        out = BASE_DIR / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== SUMMARY ===", flush=True)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
