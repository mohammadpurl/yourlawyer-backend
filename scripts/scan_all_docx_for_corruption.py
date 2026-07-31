"""
Scan all scraped .docx files for cross-contamination / duplicate bodies.

Independent of ChromaDB — disk files are the source of truth.

Usage (from your-lowyer-back):
  python scripts/scan_all_docx_for_corruption.py
  python scripts/scan_all_docx_for_corruption.py --folder "../data-scrapping-law/outputs"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_FOLDER = (
    BASE_DIR.parent / "data-scrapping-law" / "outputs"
)
OUT_DEFAULT = BASE_DIR / "storage" / "full_corpus_corruption_scan.json"

CONTAMINATION_MARKERS = [
    "برنامه هفتم",
    "برنامه پنجساله هفتم",
    "برنامه پيشرفت",
    "برنامه پیشرفت",
]

INVALID = re.compile(r"\s+")


def _norm(text: str) -> str:
    return INVALID.sub(" ", (text or "").replace("\u200c", " ")).strip()


def extract_docx_text(path: Path, max_chars: int = 8000) -> str:
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    total = 0
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        parts.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return "\n".join(parts)


def content_signature(text: str) -> str:
    """Stable signature: hash of first ~200 normalized chars after title-ish head."""
    n = _norm(text)
    # Skip first heading-ish chunk if short (title often first paragraph)
    body = n
    if len(n) > 80:
        # drop first 40 chars (often the list title repeated) then take 200
        body = n[40:240] if len(n) > 240 else n[40:]
    if len(body) < 40:
        body = n[:200]
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def title_looks_like_barnameh(name: str) -> bool:
    n = _norm(name).replace("ي", "ی").replace("ك", "ک")
    return ("برنامه هفتم" in n) or ("برنامه پنجساله هفتم" in n) or ("برنامه پیشرفت" in n)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan scraped docx for corruption")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--output", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args()

    folder: Path = args.folder
    if not folder.is_absolute():
        folder = (BASE_DIR / folder).resolve()
    if not folder.exists():
        print(f"Folder not found: {folder}", flush=True)
        return 1

    files = sorted(folder.rglob("*.docx"))
    total = len(files)
    print(f"Scanning {total} docx under {folder}", flush=True)

    sig_to_files: dict[str, list[str]] = defaultdict(list)
    sig_to_snippet: dict[str, str] = {}
    sig_counts: Counter[str] = Counter()

    barnameh_wrong_title = 0
    barnameh_ok_title = 0
    failed = 0
    failed_samples: list[str] = []
    marker_hits = 0

    t0 = time.time()
    for i, path in enumerate(files, 1):
        rel = path.relative_to(folder).as_posix()
        try:
            text = extract_docx_text(path)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if len(failed_samples) < 20:
                failed_samples.append(f"{rel}: {exc}")
            continue

        sig = content_signature(text)
        sig_counts[sig] += 1
        if len(sig_to_files[sig]) < 30:
            sig_to_files[sig].append(rel)
        if sig not in sig_to_snippet:
            sig_to_snippet[sig] = _norm(text)[40:180] if len(_norm(text)) > 40 else _norm(text)[:140]

        has_marker = any(m in text for m in CONTAMINATION_MARKERS) or any(
            m.replace("ي", "ی") in text.replace("ي", "ی") for m in CONTAMINATION_MARKERS
        )
        # also Arabic Yeh variants already in markers list
        if "برنامه هفتم" in text or "برنامه پنجساله هفتم" in text:
            has_marker = True
        if has_marker:
            marker_hits += 1
            if title_looks_like_barnameh(path.stem):
                barnameh_ok_title += 1
            else:
                barnameh_wrong_title += 1

        if i % args.progress_every == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / max(elapsed, 1)
            print(
                f"  {i}/{total} ({100*i/total:.1f}%) "
                f"{rate:.0f} files/s  marker_hits={marker_hits} "
                f"wrong_title_barnameh={barnameh_wrong_title}",
                flush=True,
            )

    # Duplicate groups: signature appears >1 time
    duplicate_groups = []
    for sig, count in sig_counts.most_common():
        if count < 2:
            continue
        duplicate_groups.append(
            {
                "signature": sig,
                "file_count": count,
                "sample_snippet": sig_to_snippet.get(sig, ""),
                "sample_files": sig_to_files.get(sig, [])[:15],
                "looks_like_barnameh": any(
                    m in (sig_to_snippet.get(sig) or "") for m in ("برنامه هفتم", "پنجساله هفتم", "پیشرفت")
                ),
            }
        )

    files_in_duplicate_groups = sum(g["file_count"] for g in duplicate_groups)
    # "suspicious" = wrong-title barnameh OR in a large duplicate cluster (>=10)
    large_dup_threshold = 10
    large_dup_files = sum(
        g["file_count"] for g in duplicate_groups if g["file_count"] >= large_dup_threshold
    )

    # Unique content that is duplicated vs singleton
    unique_bodies = len(sig_counts)
    singleton_files = sum(1 for c in sig_counts.values() if c == 1)

    scanned_ok = total - failed
    pct_wrong_barnameh = round(100.0 * barnameh_wrong_title / scanned_ok, 2) if scanned_ok else 0.0
    pct_any_marker = round(100.0 * marker_hits / scanned_ok, 2) if scanned_ok else 0.0
    pct_in_large_dup = round(100.0 * large_dup_files / scanned_ok, 2) if scanned_ok else 0.0
    # Primary corruption metric requested: wrong title + barnameh, plus extreme duplication
    suspicious = max(barnameh_wrong_title, large_dup_files)
    # Better combined unique estimate: files that are either wrong-title-barnameh OR in largest barnameh cluster
    top_barnameh_group = next(
        (g for g in duplicate_groups if g.get("looks_like_barnameh")), None
    )
    top_barnameh_count = top_barnameh_group["file_count"] if top_barnameh_group else 0

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "total_files": total,
        "scanned_ok": scanned_ok,
        "failed_reads": failed,
        "failed_samples": failed_samples,
        "unique_content_signatures": unique_bodies,
        "singleton_files": singleton_files,
        "files_in_any_duplicate_group": files_in_duplicate_groups,
        "files_in_large_duplicate_groups_ge10": large_dup_files,
        "files_with_barnameh_markers": marker_hits,
        "files_barnameh_but_title_is_something_else": barnameh_wrong_title,
        "files_barnameh_and_title_matches": barnameh_ok_title,
        "percentages": {
            "pct_files_with_barnameh_markers": pct_any_marker,
            "pct_wrong_title_barnameh": pct_wrong_barnameh,
            "pct_in_large_duplicate_groups_ge10": pct_in_large_dup,
            "primary_corruption_estimate_pct": pct_wrong_barnameh,
            "note": "primary_corruption_estimate_pct = files whose body is برنامه هفتم but filename is not",
        },
        "largest_duplicate_groups": duplicate_groups[:25],
        "largest_barnameh_duplicate_group_size": top_barnameh_count,
    }

    out: Path = args.output
    if not out.is_absolute():
        out = BASE_DIR / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also write ID list for rescrape targeting (from wrong-title barnameh files in largest groups)
    id_list: list[str] = []
    id_re = re.compile(r"(?:^|/)(\d{6,})_")
    for g in duplicate_groups[:5]:
        for f in g.get("sample_files") or []:
            m = id_re.search(f)
            if m:
                id_list.append(m.group(1))
    # Full ID extraction from all wrong-title samples would need storing all paths —
    # write a companion lightweight list while scanning was done only for samples.
    # Re-scan signatures: write all paths for the top signature only via second pass flag.
    print(json.dumps(report["percentages"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
