"""
تحلیل توزیع rerank_score بین chunkهای relevant/irrelevant برچسب‌خورده
و پیشنهاد threshold. فقط پیشنهاد می‌دهد — تصمیم نهایی با بازبینی انسانی است.

Usage:
  python eval/analyze_thresholds.py
  python eval/analyze_thresholds.py --path eval/results/relevance_scores_for_labeling.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LABELED_PATH = (
    Path(__file__).resolve().parent / "results" / "relevance_scores_for_labeling.jsonl"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=LABELED_PATH)
    args = parser.parse_args()

    if not args.path.exists():
        print(f"File not found: {args.path}", file=sys.stderr)
        print("Run collect_relevance_scores.py first, then label rows.", file=sys.stderr)
        return 1

    with open(args.path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    unlabeled = [r for r in rows if r.get("label") is None]
    if unlabeled:
        print(
            f"WARNING: {len(unlabeled)}/{len(rows)} rows still unlabeled. "
            "Label all rows before trusting a threshold."
        )
        # Continue with labeled subset for a partial peek
        rows = [r for r in rows if r.get("label") in {"relevant", "irrelevant"}]
        if not rows:
            print("No labeled rows yet. Aborting.")
            return 1

    relevant_scores = sorted(
        float(r["rerank_score"]) for r in rows if r.get("label") == "relevant"
    )
    irrelevant_scores = sorted(
        float(r["rerank_score"]) for r in rows if r.get("label") == "irrelevant"
    )

    print(f"Labeled rows used: {len(rows)}")
    print(f"relevant count: {len(relevant_scores)}")
    print(f"irrelevant count: {len(irrelevant_scores)}")
    print(
        f"min relevant: {min(relevant_scores) if relevant_scores else 'N/A'}"
    )
    print(
        f"max irrelevant: {max(irrelevant_scores) if irrelevant_scores else 'N/A'}"
    )

    suggested = None
    if relevant_scores and irrelevant_scores:
        gap_low = max(irrelevant_scores)
        gap_high = min(relevant_scores)
        if gap_high > gap_low:
            suggested = (gap_low + gap_high) / 2
            print(f"\nClean gap found between {gap_low:.4f} and {gap_high:.4f}")
            print(f"Suggested threshold: {suggested:.4f}")
        else:
            # Overlap: conservative suggestion near high end of irrelevant
            suggested = gap_low
            print("\nOverlap — no clean gap.")
            print(
                "A single threshold may not be enough; consider a better reranker "
                "or domain features. Prefer a conservative threshold near the "
                "highest irrelevant score to reduce false negatives."
            )
            print(f"Conservative suggested threshold (max irrelevant): {suggested:.4f}")

        # Simple sweep: for each candidate cut, count FP/FN on labeled set
        candidates = sorted(set(relevant_scores + irrelevant_scores))
        print("\n--- threshold sweep (keep score >= t) ---")
        print("t\tkept_rel\tdrop_rel(FN)\tkept_irr(FP)\tdrop_irr")
        for t in candidates:
            kept_rel = sum(1 for s in relevant_scores if s >= t)
            drop_rel = len(relevant_scores) - kept_rel
            kept_irr = sum(1 for s in irrelevant_scores if s >= t)
            drop_irr = len(irrelevant_scores) - kept_irr
            print(
                f"{t:.4f}\t{kept_rel}\t{drop_rel}\t{kept_irr}\t{drop_irr}"
            )

    print("\n--- top irrelevant (high scores first) ---")
    irr = sorted(
        [r for r in rows if r.get("label") == "irrelevant"],
        key=lambda r: float(r["rerank_score"]),
        reverse=True,
    )[:10]
    for r in irr:
        print(f"{float(r['rerank_score']):.4f}  {r.get('source')}")

    print("\n--- lowest relevant ---")
    rel = sorted(
        [r for r in rows if r.get("label") == "relevant"],
        key=lambda r: float(r["rerank_score"]),
    )[:10]
    for r in rel:
        print(f"{float(r['rerank_score']):.4f}  {r.get('source')}")

    print(
        "\nThis script only suggests. Do NOT enable ENABLE_MIN_RELEVANCE_FILTER "
        "in production until Leila confirms the number."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
