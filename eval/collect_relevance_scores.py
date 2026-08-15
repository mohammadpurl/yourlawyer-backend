"""
اجرای retrieve+rerank (بدون generate و بدون فیلتر آستانه) روی eval set
و ذخیره chunkها + rerank_score برای برچسب‌گذاری دستی.

Read-only نسبت به Chroma/corpus. چیزی در DB اصلی نمی‌نویسد.

Usage:
  python eval/collect_relevance_scores.py
  python eval/collect_relevance_scores.py --ids eo-001,dm-001
  python eval/collect_relevance_scores.py --limit-questions 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

EVAL_SET_PATH = Path(__file__).resolve().parent / "hard_questions_eval_set.jsonl"
OUTPUT_PATH = (
    Path(__file__).resolve().parent / "results" / "relevance_scores_for_labeling.jsonl"
)

RELEVANT_CATEGORIES = {"expert_opinion_required", "domain_mismatch_prone"}


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


def load_eval_set(path: Path = EVAL_SET_PATH) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _chunk_id(doc) -> str:
    meta = getattr(doc, "metadata", None) or {}
    h = meta.get("content_hash")
    if h:
        return str(h)[:24]
    raw = (getattr(doc, "page_content", "") or "")[:500]
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def retrieve_and_rerank(question: str) -> list[dict]:
    """
    همان مسیر production برای retrieve (+ workplace expansion) و score_documents.
    عمداً فیلتر MIN_SOURCE_RELEVANCE_SCORE را اعمال نمی‌کند تا توزیع کامل امتیازها
    برای برچسب‌گذاری و انتخاب threshold دیده شود.
    """
    from app.core.config import DEFAULT_TOP_K, RERANKER_ENABLED
    from app.services.enhanced_retrieval import EnhancedRetriever
    from app.services.rag import (
        _WORKPLACE_EXTRA_QUERIES,
        _dedupe_docs,
        _needs_workplace_expansion,
    )
    from app.services.reranker import score_documents

    k = DEFAULT_TOP_K
    retrieve_k = k * 2 if RERANKER_ENABLED else k
    retriever = EnhancedRetriever(enable_domain_filter=False)
    docs = list(retriever.retrieve(question, k=retrieve_k) or [])

    if _needs_workplace_expansion(question):
        expanded = list(docs)
        for extra_q in _WORKPLACE_EXTRA_QUERIES:
            expanded.extend(
                retriever.retrieve(extra_q, k=max(4, retrieve_k // 2)) or []
            )
        docs = _dedupe_docs(expanded)

    scored = score_documents(question, docs)
    # Keep top candidates similar to production shortlist size (before filter)
    scored = scored[: max(retrieve_k, k * 2)]

    rows: list[dict] = []
    for doc, score in scored:
        meta = getattr(doc, "metadata", None) or {}
        text = getattr(doc, "page_content", "") or ""
        # Strip e5 passage prefix for readability
        if text.startswith("passage: "):
            text = text[len("passage: ") :]
        rows.append(
            {
                "chunk_id": _chunk_id(doc),
                "source": str(meta.get("law_name") or meta.get("source") or ""),
                "domain": meta.get("domain"),
                "subdomain": meta.get("subdomain"),
                "text_preview": text[:200].replace("\n", " "),
                "rerank_score": round(float(score), 6),
                "scorer": "cross_encoder" if RERANKER_ENABLED else "keyword",
            }
        )
    return rows


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=str, default="")
    parser.add_argument("--limit-questions", type=int, default=None)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=EVAL_SET_PATH,
    )
    args = parser.parse_args()

    items = load_eval_set(args.eval_set)
    items = [i for i in items if i.get("category") in RELEVANT_CATEGORIES]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [i for i in items if i["id"] in want]
    if args.limit_questions is not None:
        items = items[: args.limit_questions]

    print(
        f"Collecting scores for {len(items)} questions "
        f"(categories={sorted(RELEVANT_CATEGORIES)}) ...",
        flush=True,
    )

    rows = []
    for item in items:
        qid = item["id"]
        print(f"  {qid} ...", flush=True)
        try:
            chunks = retrieve_and_rerank(item["question"])
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {qid}: {e}", flush=True)
            continue
        for c in chunks:
            rows.append(
                {
                    "eval_id": qid,
                    "question": item["question"],
                    "category": item.get("category"),
                    "chunk_id": c["chunk_id"],
                    "source": c["source"],
                    "domain": c.get("domain"),
                    "subdomain": c.get("subdomain"),
                    "text_preview": c["text_preview"][:200],
                    "rerank_score": c["rerank_score"],
                    "scorer": c.get("scorer"),
                    "label": None,  # "relevant" | "irrelevant" — گام ۲ دستی
                }
            )
        print(f"  {qid}: {len(chunks)} chunks", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"{len(rows)} chunks for labeling saved to {args.out}")
    print(
        "Fill each row's 'label' with 'relevant' or 'irrelevant', "
        "then run: python eval/analyze_thresholds.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
