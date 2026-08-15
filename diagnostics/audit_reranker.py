"""
Diagnose whether the CrossEncoder reranker discriminates relevant vs irrelevant Persian legal text.

Usage:
  python diagnostics/audit_reranker.py
  python diagnostics/audit_reranker.py --model cross-encoder/ms-marco-MiniLM-L-6-v2
  python diagnostics/audit_reranker.py --model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1

ROOT CAUSE CONTEXT (see app/services/reranker.py):
  Default was English ``ms-marco-MiniLM-L-6-v2``. On Persian legal pairs it often
  emits large positive logits for BOTH relevant and irrelevant chunks; after
  sigmoid that collapses to ~0.999 for everything — so threshold filtering is
  meaningless. This script isolates score_documents() (no full RAG).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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


QUERY = "ضمان قهری در قانون مدنی چیست"

RELEVANT_TEXT = (
    "ماده ۳۰۷ قانون مدنی - امور ذیل موجب ضمان قهری است: "
    "۱ - غصب و آنچه در حکم غصب است. "
    "۲ - اتلاف. "
    "۳ - تسبیب. "
    "۴ - استیفاء. "
    "ماده ۳۰۸ - غصب استیلاء بر حق غیر است به نحو عدوان. "
    "اثبات ید بر مال غیر بدون مجوز هم در حکم غصب است."
)

IRRELEVANT_TEXT = (
    "ماده ۴ آیین‌نامه نحوه اجرای وظایف ناشی از الحاق به مقاوله‌نامه کار دریایی: "
    "مالکان کشتی‌های ایرانی مشمول مقاوله‌نامه مکلفند برای اطمینان از اجرای تعهد "
    "و مسئولیت بازگرداندن دریانوردان شاغل در کشتی‌های مزبور به وطن طبق قرارداد کار "
    "اقدامات لازم را به عمل آورند."
)


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Audit reranker discrimination")
    parser.add_argument(
        "--model",
        default=None,
        help="Override RERANKER_MODEL for this run (forces reload)",
    )
    parser.add_argument(
        "--delta-warn",
        type=float,
        default=0.05,
        help="Warn if |score_rel - score_irr| below this",
    )
    parser.add_argument(
        "--delta-good",
        type=float,
        default=0.3,
        help="Celebrate if delta exceeds this",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BASE_DIR / "diagnostics" / "reranker_audit_latest.json",
    )
    args = parser.parse_args()

    if args.model:
        os.environ["RERANKER_MODEL"] = args.model
        os.environ["RERANKER_ENABLED"] = "true"

    # Force fresh import / reload of module globals after env override
    import importlib
    import app.core.config as cfg

    importlib.reload(cfg)
    import app.services.reranker as rr

    importlib.reload(rr)
    rr._reranker_model = None
    rr._reranker_loading_attempted = False

    from langchain_core.documents import Document

    docs = [
        Document(
            page_content=RELEVANT_TEXT,
            metadata={"law_name": "قانون مدنی", "source": "قانون مدنی", "label": "relevant"},
        ),
        Document(
            page_content=IRRELEVANT_TEXT,
            metadata={
                "law_name": "آیین نامه کار دریایی",
                "source": "آیین نامه کار دریایی",
                "label": "irrelevant",
            },
        ),
    ]

    model_name = cfg.RERANKER_MODEL
    print(f"Query: {QUERY}")
    print(f"RERANKER_ENABLED={cfg.RERANKER_ENABLED}")
    print(f"RERANKER_MODEL={model_name}")
    print(f"MIN_SOURCE_RELEVANCE_SCORE={cfg.MIN_SOURCE_RELEVANCE_SCORE}")
    print()

    model = rr.get_reranker_model()
    print(f"Loaded CrossEncoder: {bool(model)}")

    # Raw logits (if CE available) + final pipeline scores
    raw_logits = None
    if model is not None:
        pairs = [[QUERY, d.page_content] for d in docs]
        raw = model.predict(pairs)
        raw_logits = [float(x) for x in raw]
        print(f"raw_logits (relevant, irrelevant) = {raw_logits}")
        print(
            f"sigmoid(raw) = {[round(rr._sigmoid(x), 6) for x in raw_logits]}"
        )

    scored = rr.score_documents(QUERY, docs)
    by_label = {}
    for doc, score in scored:
        label = (doc.metadata or {}).get("label")
        by_label[label] = float(score)
        print(f"score({label:10s}) = {score:.6f}  law={doc.metadata.get('law_name')}")

    s_rel = by_label.get("relevant", 0.0)
    s_irr = by_label.get("irrelevant", 0.0)
    delta = abs(s_rel - s_irr)
    print()
    print(f"score(relevant)   = {s_rel:.6f}")
    print(f"score(irrelevant) = {s_irr:.6f}")
    print(f"delta = {delta:.6f}", end="")

    verdict = "ok"
    if delta < args.delta_warn:
        verdict = "broken"
        print(
            "  ⚠️ RERANKER NOT DISCRIMINATING — مشکل از خود reranker است "
            "(نه فقط threshold)"
        )
    elif delta >= args.delta_good:
        verdict = "good"
        print("  ✅ meaningful discrimination")
    else:
        verdict = "weak"
        print("  ⚡ weak discrimination — threshold still unreliable")

    # Ranking check
    rank_ok = s_rel > s_irr
    print(f"ranks_relevant_first = {rank_ok}")

    report = {
        "query": QUERY,
        "model": model_name,
        "raw_logits": raw_logits,
        "score_relevant": s_rel,
        "score_irrelevant": s_irr,
        "delta": delta,
        "verdict": verdict,
        "ranks_relevant_first": rank_ok,
        "delta_warn": args.delta_warn,
        "delta_good": args.delta_good,
        "notes": (
            "English ms-marco-MiniLM on Persian often saturates sigmoid≈1.0. "
            "Prefer multilingual mmarco / hybrid keyword blend (see reranker.py)."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {args.out}")
    return 0 if verdict != "broken" else 1


if __name__ == "__main__":
    raise SystemExit(main())
