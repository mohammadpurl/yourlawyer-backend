"""
Backfill Chroma ``domain`` / ``subdomain`` metadata on legal-texts-v2.

Does NOT re-embed — only ``collection.update(ids=..., metadatas=...)``.

Usage:
  python scripts/backfill_domain_tags.py --dry-run --limit 500
  python scripts/backfill_domain_tags.py
  python scripts/backfill_domain_tags.py --sample-validate 10

Unknown laws → domain=\"unclassified\" (not null).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
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
    parser = argparse.ArgumentParser(description="Backfill domain tags in Chroma")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None, help="Max chunks to process")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute mapping stats without writing",
    )
    parser.add_argument(
        "--sample-validate",
        type=int,
        default=10,
        help="Print N random mapped samples at end",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BASE_DIR / "storage" / "backfill_domain_tags_report.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even if domain already set to a non-null taxonomy value",
    )
    args = parser.parse_args()

    from app.core.config import CHROMA_COLLECTION, PERSIST_DIRECTORY
    from app.services.domain_law_map import map_law_to_domain
    from app.services.vectorstore import _get_chroma_collection

    collection = _get_chroma_collection(CHROMA_COLLECTION)
    if collection is None:
        print(
            f"ERROR: collection {CHROMA_COLLECTION!r} not found under {PERSIST_DIRECTORY}",
            file=sys.stderr,
        )
        return 1

    total = collection.count()
    print(f"Collection={CHROMA_COLLECTION} count={total} dry_run={args.dry_run}")

    domain_counts: Counter[str] = Counter()
    slug_counts: Counter[str] = Counter()
    skipped_already = 0
    updated = 0
    null_before = 0
    samples: list[dict[str, Any]] = []
    processed = 0
    offset = 0
    batch = args.batch_size

    while True:
        if args.limit is not None and processed >= args.limit:
            break
        take = batch
        if args.limit is not None:
            take = min(batch, args.limit - processed)
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

        upd_ids: list[str] = []
        upd_metas: list[dict] = []

        for i, doc_id in enumerate(ids):
            meta = dict(metadatas[i] or {})
            text = documents[i] if i < len(documents) else ""
            old_domain = meta.get("domain")
            if old_domain in (None, "", "null", "None", "نامشخص"):
                null_before += 1
            elif not args.force and old_domain not in ("unclassified",):
                # Already tagged with a concrete domain — skip unless --force
                skipped_already += 1
                domain_counts[str(old_domain)] += 1
                continue

            mapped = map_law_to_domain(
                law_name=str(meta.get("law_name") or ""),
                source=str(meta.get("source") or ""),
                text_preview=(text or "")[:500],
            )
            new_domain = mapped["domain"]
            new_sub = mapped.get("subdomain")
            slug = mapped.get("domain_slug") or "unclassified"

            domain_counts[str(new_domain)] += 1
            slug_counts[str(slug)] += 1

            new_meta = dict(meta)
            new_meta["domain"] = new_domain
            if new_sub:
                new_meta["subdomain"] = new_sub
            new_meta["domain_slug"] = slug
            new_meta["domain_tag_method"] = mapped.get("method")

            upd_ids.append(doc_id)
            upd_metas.append(new_meta)
            if len(samples) < max(50, args.sample_validate * 3):
                samples.append(
                    {
                        "id": doc_id[:24],
                        "law_name": meta.get("law_name") or meta.get("source"),
                        "old_domain": old_domain,
                        "new_domain": new_domain,
                        "subdomain": new_sub,
                        "slug": slug,
                    }
                )

        if upd_ids and not args.dry_run:
            # Chroma update in sub-batches
            step = 100
            for j in range(0, len(upd_ids), step):
                collection.update(
                    ids=upd_ids[j : j + step],
                    metadatas=upd_metas[j : j + step],
                )
            updated += len(upd_ids)
        elif upd_ids:
            updated += len(upd_ids)  # would-update count in dry-run

        processed += len(ids)
        offset += len(ids)
        print(
            f"  offset={offset} processed={processed} "
            f"updated/planned={updated} skipped_already={skipped_already}",
            flush=True,
        )
        if len(ids) < take:
            break

    tagged = sum(c for d, c in domain_counts.items() if d not in ("unclassified", "نامشخص"))
    unclassified = domain_counts.get("unclassified", 0) + domain_counts.get("نامشخص", 0)
    denom = max(1, tagged + unclassified)
    pct_tagged = 100.0 * tagged / denom
    pct_unclassified = 100.0 * unclassified / denom
    pct_null_cleared = 100.0 * (1 - (null_before / max(1, processed))) if processed else 0

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "collection": CHROMA_COLLECTION,
        "dry_run": args.dry_run,
        "total_in_collection": total,
        "processed": processed,
        "updated_or_planned": updated,
        "skipped_already_tagged": skipped_already,
        "null_or_unknown_before_in_batch": null_before,
        "domain_counts": dict(domain_counts),
        "slug_counts": dict(slug_counts),
        "pct_tagged_of_mapped": round(pct_tagged, 2),
        "pct_unclassified_of_mapped": round(pct_unclassified, 2),
        "note": (
            "pct_* are over chunks this run assigned/counted via map "
            "(plus already-tagged when skipped). Re-run without --limit for full corpus."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Backfill report ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nTagged≈{pct_tagged:.1f}% | unclassified≈{pct_unclassified:.1f}%")
    print(f"Wrote {args.out}")

    if samples and args.sample_validate > 0:
        print("\n=== Sample validation ===")
        for row in random.sample(samples, min(args.sample_validate, len(samples))):
            print(
                f"  {row['law_name']!r}: {row['old_domain']!r} → "
                f"{row['new_domain']!r}/{row.get('subdomain')} ({row['slug']})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
