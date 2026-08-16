"""
Audit Chroma chunk text for encoding corruption (presentation forms, /uXXXX, etc.).

Scans ``legal-texts-v2`` (or ``--collection``) without re-embedding.
Optionally purge bad chunk IDs with ``--purge`` (after reviewing the report).

Usage:
  python scripts/audit_chroma_encoding.py --limit 5000 --dry-run
  python scripts/audit_chroma_encoding.py
  python scripts/audit_chroma_encoding.py --purge --purge-confirm YES_PURGE_BAD_ENCODING
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


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


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Audit Chroma encoding quality")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--collection",
        default=None,
        help="Override CHROMA_COLLECTION",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BASE_DIR / "storage" / "encoding_audit_report.json",
    )
    parser.add_argument(
        "--sample-bad",
        type=int,
        default=30,
        help="Max bad examples to keep in report",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete flagged chunk IDs from Chroma (requires --purge-confirm)",
    )
    parser.add_argument(
        "--purge-confirm",
        default="",
        help="Must equal YES_PURGE_BAD_ENCODING to actually delete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias: never purge even if --purge set",
    )
    args = parser.parse_args()

    from app.core.config import CHROMA_COLLECTION, PERSIST_DIRECTORY
    from app.services.ingestion import assess_extracted_text_quality
    from app.services.vectorstore import _get_chroma_collection, strip_e5_prefix

    collection_name = args.collection or CHROMA_COLLECTION
    collection = _get_chroma_collection(collection_name)
    if collection is None:
        print(
            f"ERROR: collection {collection_name!r} not found under {PERSIST_DIRECTORY}",
            file=sys.stderr,
        )
        return 1

    total = collection.count()
    print(f"Collection={collection_name} count={total}")

    reason_counts: Counter[str] = Counter()
    bad_by_source: Counter[str] = Counter()
    bad_ids: list[str] = []
    samples: list[dict[str, Any]] = []
    scanned = 0
    ok_count = 0
    offset = 0
    batch = args.batch_size

    while True:
        if args.limit is not None and scanned >= args.limit:
            break
        take = batch
        if args.limit is not None:
            take = min(batch, args.limit - scanned)
        result = collection.get(
            include=["metadatas", "documents"],
            limit=take,
            offset=offset,
        )
        ids = result.get("ids") or []
        if not ids:
            break
        metadatas = result.get("metadatas") or []
        documents = result.get("documents") or []

        for i, doc_id in enumerate(ids):
            meta = metadatas[i] or {}
            raw = documents[i] if i < len(documents) else ""
            text = strip_e5_prefix(raw or "")
            q = assess_extracted_text_quality(text)
            scanned += 1
            if q["ok"]:
                # Extra: presentation forms remaining after ingest (should be rare)
                if q.get("presentation_forms", 0) > 20:
                    reason_counts["residual_presentation_forms"] += 1
                    bad_ids.append(doc_id)
                    src = str(meta.get("law_name") or meta.get("source") or "?")
                    bad_by_source[src] += 1
                    if len(samples) < args.sample_bad:
                        samples.append(
                            {
                                "id": doc_id[:32],
                                "source": src,
                                "reasons": ["residual_presentation_forms"],
                                "chars": q["chars"],
                                "persian": q["persian_letters"],
                                "presentation": q["presentation_forms"],
                                "preview": text[:180].replace("\n", " "),
                            }
                        )
                else:
                    ok_count += 1
                continue

            for r in q.get("reasons") or ["unknown"]:
                reason_counts[r] += 1
            bad_ids.append(doc_id)
            src = str(meta.get("law_name") or meta.get("source") or "?")
            bad_by_source[src] += 1
            if len(samples) < args.sample_bad:
                samples.append(
                    {
                        "id": doc_id[:32],
                        "source": src,
                        "reasons": q.get("reasons"),
                        "chars": q["chars"],
                        "persian": q["persian_letters"],
                        "literal_u": q.get("literal_unicode_escapes"),
                        "presentation": q.get("presentation_forms"),
                        "preview": text[:180].replace("\n", " "),
                    }
                )

        offset += len(ids)
        print(
            f"  offset={offset} scanned={scanned} ok={ok_count} bad={len(bad_ids)}",
            flush=True,
        )
        if len(ids) < take:
            break

    purged = 0
    do_purge = (
        args.purge
        and not args.dry_run
        and args.purge_confirm == "YES_PURGE_BAD_ENCODING"
        and bad_ids
    )
    if args.purge and not do_purge:
        print(
            "Purge skipped (need --purge --purge-confirm YES_PURGE_BAD_ENCODING "
            "and not --dry-run)",
            file=sys.stderr,
        )
    if do_purge:
        step = 100
        for j in range(0, len(bad_ids), step):
            collection.delete(ids=bad_ids[j : j + step])
        purged = len(bad_ids)
        print(f"Purged {purged} bad chunks")

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "collection": collection_name,
        "persist_directory": PERSIST_DIRECTORY,
        "total_in_collection": total,
        "scanned": scanned,
        "ok": ok_count,
        "bad": len(bad_ids),
        "bad_rate": round(len(bad_ids) / scanned, 4) if scanned else None,
        "reason_counts": dict(reason_counts),
        "bad_by_source_top": bad_by_source.most_common(40),
        "samples": samples,
        "purged": purged,
        "gate_layer1": {
            "near_zero_bad_encoding": len(bad_ids) == 0
            or (scanned > 0 and len(bad_ids) / scanned < 0.001),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in (
        "scanned", "ok", "bad", "bad_rate", "reason_counts", "purged"
    )}, ensure_ascii=False, indent=2))
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
