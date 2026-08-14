"""
اجرای eval set در برابر پایپ‌لاین فعلی و تولید گزارش مقایسه‌ای.

قوانین:
- به کورپوس / Chroma چیزی نمی‌نویسد (read-only نسبت به وکتورها).
- حالت ``detect`` و ``retrieve`` بدون فراخوانی LLM generation هستند.
- حالت ``full`` همان ``build_rag_chain`` پروداکشن را صدا می‌زند و ممکن است
  مصرف سهمیه OpenAI / لاگ usage در DB ثبت کند — قبل از اجرا آگاه باشید.

امتیاز خودکار فقط چک‌های ساختاری است. قضاوت کیفیت محتوایی پاسخ باید توسط
انسان (لیلا / وکیل) انجام شود — این اسکریپت جایگزین بازبینی انسانی نیست.

Usage:
  python eval/run_eval.py --mode detect
  python eval/run_eval.py --mode detect --ids eo-001,bl-001
  python eval/run_eval.py --mode full --limit 3
  python eval/run_eval.py --mode detect --compare eval/results/baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

EVAL_SET_PATH = Path(__file__).resolve().parent / "hard_questions_eval_set.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


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
            if not line:
                continue
            items.append(json.loads(line))
    return items


def run_single(item: dict, *, mode: str) -> dict:
    """
    سوال را از مسیر واقعی پروژه اجرا کن.

    mode=detect: فقط detect_expert_opinion_domain (بدون LLM/Chroma write)
    mode=retrieve: classify+retrieve+rerank بدون generate
    mode=full: build_rag_chain پروداکشن (ممکن است usage در DB بنویسد)
    """
    question = item["question"]
    from app.config.expert_opinion_domains import (
        detect_expert_opinion_domain,
        expert_opinion_api_payload,
    )

    expert_domain = detect_expert_opinion_domain(question)
    expert_payload = expert_opinion_api_payload(expert_domain)

    if mode == "detect":
        return {
            "mode": mode,
            "answer": None,
            "sources": [],
            "expert_opinion_required": expert_payload,
            "no_context": None,
            "grounded": None,
        }

    if mode == "retrieve":
        from app.core.config import DEFAULT_TOP_K, RERANKER_ENABLED
        from app.services.enhanced_retrieval import EnhancedRetriever
        from app.services.rag import (
            _needs_workplace_expansion,
            _WORKPLACE_EXTRA_QUERIES,
            _dedupe_docs,
        )
        from app.services.reranker import rerank_documents, score_documents, filter_by_min_score
        from app.services.taxonomy import classify_confident

        tax = classify_confident(question)
        retriever = EnhancedRetriever(enable_domain_filter=False)
        k = DEFAULT_TOP_K
        retrieve_k = k * 2 if RERANKER_ENABLED else k
        docs = retriever.retrieve(question, k=retrieve_k)
        if _needs_workplace_expansion(question):
            expanded = list(docs or [])
            for extra_q in _WORKPLACE_EXTRA_QUERIES:
                expanded.extend(retriever.retrieve(extra_q, k=max(4, retrieve_k // 2)) or [])
            docs = _dedupe_docs(expanded)
        if docs:
            if RERANKER_ENABLED:
                docs = rerank_documents(question, docs, top_k=k)
            else:
                docs = filter_by_min_score(score_documents(question, docs))[:k]
        sources = []
        for d in docs or []:
            meta = getattr(d, "metadata", None) or {}
            sources.append(str(meta.get("law_name") or meta.get("source") or "")[:120])
        return {
            "mode": mode,
            "answer": None,
            "sources": sources,
            "retrieved_count": len(docs or []),
            "taxonomy": {
                "domain": tax.get("domain"),
                "subdomain": tax.get("subdomain"),
                "confidence": tax.get("confidence"),
            },
            "expert_opinion_required": expert_payload,
            "no_context": not bool(docs),
            "grounded": None,
        }

    # full pipeline
    from app.core.config import DEFAULT_TOP_K, RERANKER_ENABLED, OPENAI_API_KEY
    from app.services.rag import build_rag_chain

    user = None
    db = None
    if OPENAI_API_KEY:
        from app.core.database import SessionLocal
        from app.models.user import User

        db = SessionLocal()
        try:
            user_id = os.getenv("EVAL_USER_ID")
            if user_id:
                user = db.get(User, int(user_id))
            if user is None:
                user = (
                    db.query(User)
                    .filter(User.is_admin.is_(True))  # type: ignore[attr-defined]
                    .first()
                )
            if user is None:
                user = db.query(User).first()
            if user is None:
                return {
                    "mode": mode,
                    "error": "No user found for full eval (set EVAL_USER_ID)",
                    "expert_opinion_required": expert_payload,
                }
            rag = build_rag_chain(
                k=DEFAULT_TOP_K,
                use_enhanced_retrieval=True,
                use_reranking=RERANKER_ENABLED,
                user=user,
                db=db,
            )
            result = rag(question)
            if isinstance(result, dict):
                # Ensure expert flag present even if older cache omitted it
                if expert_payload and not result.get("expert_opinion_required"):
                    result["expert_opinion_required"] = expert_payload
                result["mode"] = mode
                return result
            return {"mode": mode, "answer": str(result), "expert_opinion_required": expert_payload}
        finally:
            db.close()

    rag = build_rag_chain(
        k=DEFAULT_TOP_K,
        use_enhanced_retrieval=True,
        use_reranking=RERANKER_ENABLED,
    )
    result = rag(question)
    if isinstance(result, dict):
        if expert_payload and not result.get("expert_opinion_required"):
            result["expert_opinion_required"] = expert_payload
        result["mode"] = mode
        return result
    return {"mode": mode, "answer": str(result), "expert_opinion_required": expert_payload}


_PERCENT_FABRICATE = re.compile(
    r"(?:مقصر(?:ند| است| هستند)?\s*(?:حدوداً|حدود)?\s*)?\d{1,3}\s*(?:٪|%)|"
    r"(?:٪|%)\s*\d{1,3}|"
    r"درصد\s*(?:تقصیر\s*)?(?:حدوداً\s*)?\d{1,3}",
    re.IGNORECASE,
)


def score_against_expected(item: dict, actual_output: dict) -> dict:
    """
    امتیازدهی خودکار فقط برای چک‌های ساختاری قابل اتوماسیون.
    قضاوت کیفیت محتوایی همچنان انسانی است.
    """
    checks: dict[str, Any] = {}
    expected = item.get("expected_behavior") or {}
    answer = (actual_output.get("answer") or "") if isinstance(actual_output, dict) else ""
    sources = actual_output.get("sources") or []
    sources_blob = " ".join(str(s) for s in sources)
    eo = actual_output.get("expert_opinion_required") or {}
    flag = bool(isinstance(eo, dict) and eo.get("flag") is True)

    if "should_flag_expert_opinion_required" in expected:
        want = bool(expected["should_flag_expert_opinion_required"])
        checks["flag_correctly_set"] = flag is want

    if expected.get("should_not_fabricate_percentage") and answer:
        # Allow phrases denying a fixed percentage
        deny = any(
            p in answer
            for p in (
                "درصد ثابتی",
                "عدد ثابتی",
                "قانون مشخص نکرده",
                "کارشناس",
                "تعیین می‌کند",
                "تعیین میکند",
            )
        )
        fabricated = bool(_PERCENT_FABRICATE.search(answer)) and not deny
        checks["did_not_fabricate_percentage"] = not fabricated

    if expected.get("should_state_no_fixed_percentage") and answer:
        checks["mentions_no_fixed_or_expert"] = any(
            p in answer
            for p in (
                "کارشناس",
                "درصد ثابت",
                "عدد دقیق",
                "قانون مشخص",
                "نظریه کارشناسی",
            )
        )

    if expected.get("should_admit_insufficient_sources") and answer:
        checks["admits_gap"] = any(
            p in answer
            for p in (
                "اطلاعات کافی",
                "در منابع",
                "یافت نشد",
                "پوشش",
                "موجود نیست",
            )
        )

    if expected.get("should_return_grounded_answer") and answer is not None:
        if actual_output.get("mode") in {"detect", "retrieve"}:
            checks["grounded_answer_skipped"] = True
        else:
            checks["not_empty_refuse_only"] = not (
                answer.strip().startswith("اطلاعات کافی در منابع موجود")
                and len(answer) < 120
            )
            checks["has_sources_or_grounded"] = bool(sources) or bool(
                actual_output.get("grounded")
            )

    if expected.get("should_prefer_check_law"):
        bad = any(
            x in sources_blob
            for x in ("استرداد", "مجرمین", "معاهده استرداد")
        )
        good = any(x in sources_blob for x in ("چک", "صدور چک", "اسناد تجاری"))
        if sources:
            checks["not_extradition_sources"] = not bad
            checks["has_check_related_source"] = good

    if expected.get("should_not_retrieve_extradition") and sources:
        checks["not_extradition_sources"] = not any(
            x in sources_blob for x in ("استرداد", "مجرمین")
        )

    checks["human_review_required"] = True
    return checks


def compare_runs(current: list[dict], baseline: list[dict]) -> dict:
    base_by_id = {r["id"]: r for r in baseline}
    regressions = []
    improvements = []
    for row in current:
        prev = base_by_id.get(row["id"])
        if not prev:
            continue
        cur_checks = row.get("checks") or {}
        prev_checks = prev.get("checks") or {}
        for key, val in cur_checks.items():
            if key == "human_review_required":
                continue
            old = prev_checks.get(key)
            if old is True and val is False:
                regressions.append({"id": row["id"], "check": key})
            if old is False and val is True:
                improvements.append({"id": row["id"], "check": key})
    return {"regressions": regressions, "improvements": improvements}


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Hard-questions RAG eval (read-mostly)")
    parser.add_argument(
        "--mode",
        choices=("detect", "retrieve", "full"),
        default="detect",
        help="detect=flag only; retrieve=no LLM generate; full=production RAG",
    )
    parser.add_argument("--ids", type=str, default="", help="Comma-separated item ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", type=str, default="")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: eval/results/latest_run.json)",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="Previous run JSON to diff structural checks against",
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=EVAL_SET_PATH,
    )
    args = parser.parse_args()

    items = load_eval_set(args.eval_set)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [i for i in items if i["id"] in want]
    if args.category:
        items = [i for i in items if i.get("category") == args.category]
    if args.limit is not None:
        items = items[: args.limit]

    if args.mode == "full":
        print(
            "WARNING: --mode full calls production generate and may record OpenAI "
            "usage in the database. Corpus/Chroma remain read-only.",
            file=sys.stderr,
        )

    results = []
    for item in items:
        print(f"Running {item['id']} ({item['category']}) ...", flush=True)
        try:
            actual = run_single(item, mode=args.mode)
        except Exception as e:  # noqa: BLE001
            actual = {"mode": args.mode, "error": str(e)}
        scored = score_against_expected(item, actual if isinstance(actual, dict) else {})
        results.append(
            {
                "id": item["id"],
                "category": item.get("category"),
                "question": item.get("question"),
                "expert_domain_id": item.get("expert_domain_id"),
                "checks": scored,
                "raw_output": {
                    k: actual.get(k)
                    for k in (
                        "mode",
                        "answer",
                        "sources",
                        "expert_opinion_required",
                        "no_context",
                        "grounded",
                        "retrieved_count",
                        "taxonomy",
                        "error",
                        "citation_confidence",
                    )
                    if isinstance(actual, dict) and k in actual
                },
                "gold_answer_notes": item.get("gold_answer_notes"),
                "reviewed_by": item.get("reviewed_by"),
                "human_content_review": "PENDING — automatic checks are structural only",
            }
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out or (RESULTS_DIR / "latest_run.json")
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "eval_set": str(args.eval_set),
        "n": len(results),
        "note": (
            "Automatic scores are structural only (flags, simple heuristics). "
            "Content quality must be reviewed by a human before treating a change "
            "as an improvement. Do not commit pipeline changes without comparing "
            "baseline vs current and without Leila's approval."
        ),
        "results": results,
    }

    if args.compare and args.compare.exists():
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        base_results = baseline.get("results") or baseline
        payload["diff_vs_baseline"] = compare_runs(results, base_results)

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Results saved to {out_path}")
    print(
        "Please also review answers manually (reviewed_by is empty; "
        "automatic checks are structural only)."
    )

    # Summary of structural fails
    fails = []
    for row in results:
        for k, v in (row.get("checks") or {}).items():
            if k != "human_review_required" and v is False:
                fails.append(f"{row['id']}:{k}")
    if fails:
        print("Structural failures:", ", ".join(fails))
    else:
        print("No structural check failures (human review still required).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
