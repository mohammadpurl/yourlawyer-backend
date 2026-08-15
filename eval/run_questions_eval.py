"""
Pipeline eval harness for ``eval/questions.jsonl``.

Runs each question against the real RAG path (HTTP ``POST /ask`` by default, or
in-process ``build_rag_chain``), collects QUERY_TRACE + response fields, prints
a refusal breakdown, and writes ``eval/results/<timestamp>.json``.

Safety:
  - Set ``EVAL_BASE_URL`` to local/staging only (never production by accident).
  - Default base URL is ``http://127.0.0.1:8000``.
  - OpenAI cost: respect existing quota / rate limits; use ``--limit`` for dry runs.

Usage:
  python eval/run_questions_eval.py --limit 2 --via inprocess
  python eval/run_questions_eval.py --via api
  set EVAL_BASE_URL=http://127.0.0.1:8000
  set EVAL_TOKEN=<jwt>
  python eval/run_questions_eval.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Refuse to hit known production hosts unless explicitly allowed
_BLOCKED_HOST_SNIPPETS = (
    "yourlawyeer.ir",
    "yourlawyer.ir",
    "yourlawter",
)


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


def load_questions(path: Path) -> list[dict]:
    items: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _infer_outcome_from_response(resp: dict[str, Any], trace: dict | None) -> str:
    if trace and isinstance(trace.get("generate"), dict):
        out = trace["generate"].get("outcome")
        if out:
            return str(out)
    if resp.get("response_type") == "general_guidance":
        return "general_guidance"
    if resp.get("is_error"):
        return "refused"
    if resp.get("no_context") or resp.get("refusal_reason"):
        return "refused"
    answer = resp.get("answer") or ""
    if isinstance(answer, str) and answer.strip().startswith(
        "اطلاعات کافی در منابع موجود"
    ):
        return "refused"
    conf = resp.get("citation_confidence")
    if conf in {"partial", "unverified"}:
        return "low_confidence_answered"
    return "answered"


def _load_trace_by_query_id(query_id: str | None) -> dict | None:
    if not query_id:
        return None
    from app.services.query_trace import QUERY_TRACE_PATH

    path = QUERY_TRACE_PATH
    if not path.exists():
        return None
    # Scan last ~500 lines (eval runs are sequential)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-500:]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("query_id") == query_id:
            return obj
    return None


def run_via_api(question: str, *, base_url: str, token: str, top_k: int) -> dict:
    url = base_url.rstrip("/") + "/ask"
    body = json.dumps(
        {
            "question": question,
            "top_k": top_k,
            "use_enhanced_retrieval": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {
            "answer": detail,
            "is_error": True,
            "error_code": e.code,
            "sources": [],
        }


def run_via_inprocess(question: str, *, top_k: int) -> dict:
    from app.core.config import OPENAI_API_KEY, RERANKER_ENABLED
    from app.services.rag import build_rag_chain

    user = None
    db = None
    if OPENAI_API_KEY:
        # Register all ORM mappers (same as app.main) before querying User
        import app.models.user  # noqa: F401
        import app.models.usage  # noqa: F401
        import app.models.login_history  # noqa: F401
        import app.models.template  # noqa: F401
        import app.models.citation  # noqa: F401
        import app.models.sample_document  # noqa: F401
        import app.models.payment  # noqa: F401
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
                    "answer": "No user found for eval (set EVAL_USER_ID)",
                    "is_error": True,
                    "error_code": 500,
                    "sources": [],
                }
            rag = build_rag_chain(
                k=top_k,
                use_enhanced_retrieval=True,
                use_reranking=RERANKER_ENABLED,
                user=user,
                db=db,
            )
            result = rag(question)
            return result if isinstance(result, dict) else {"answer": str(result)}
        finally:
            db.close()

    rag = build_rag_chain(
        k=top_k,
        use_enhanced_retrieval=True,
        use_reranking=RERANKER_ENABLED,
    )
    result = rag(question)
    return result if isinstance(result, dict) else {"answer": str(result)}


def _assert_safe_base_url(base_url: str, *, allow_production: bool) -> None:
    low = base_url.lower()
    if allow_production:
        return
    for snip in _BLOCKED_HOST_SNIPPETS:
        if snip in low:
            raise SystemExit(
                f"Refusing to eval against production-like host ({base_url}). "
                "Use local/staging EVAL_BASE_URL, or pass --allow-production "
                "only if you really intend to."
            )


def summarize(rows: list[dict]) -> dict[str, Any]:
    outcomes = Counter(r["actual_outcome"] for r in rows)
    by_domain: dict[str, Any] = {}
    domain_rows: dict[str, list] = defaultdict(list)
    for r in rows:
        domain_rows[r.get("domain") or "unknown"].append(r)

    refusal_reasons: Counter = Counter()
    unexpected: list[dict] = []

    for domain, drows in sorted(domain_rows.items()):
        answered = sum(1 for r in drows if r["actual_outcome"] == "answered")
        refused = sum(1 for r in drows if r["actual_outcome"] == "refused")
        guidance = sum(1 for r in drows if r["actual_outcome"] == "general_guidance")
        low = sum(1 for r in drows if r["actual_outcome"] == "low_confidence_answered")
        scores = [
            r.get("final_confidence_score")
            for r in drows
            if isinstance(r.get("final_confidence_score"), (int, float))
        ]
        reasons = Counter(
            r.get("refusal_reason")
            for r in drows
            if r["actual_outcome"] in {"refused", "general_guidance"}
            and r.get("refusal_reason")
        )
        by_domain[domain] = {
            "total": len(drows),
            "answered": answered,
            "refused": refused,
            "general_guidance": guidance,
            "low_confidence_answered": low,
            "avg_confidence": round(sum(scores) / len(scores), 3) if scores else None,
            "refusal_reasons": dict(reasons),
        }

    for r in rows:
        if r.get("refusal_reason"):
            refusal_reasons[r["refusal_reason"]] += 1
        expected = r.get("expected_outcome")
        allowed = r.get("expected_outcomes")
        if not allowed and expected:
            allowed = [expected]
        actual = r.get("actual_outcome")
        if allowed and actual and actual not in allowed:
            unexpected.append(
                {
                    "id": r["id"],
                    "expected": expected,
                    "expected_outcomes": allowed,
                    "got": actual,
                    "refusal_reason": r.get("refusal_reason"),
                    "score": r.get("final_confidence_score"),
                    "threshold": r.get("confidence_threshold"),
                }
            )

    return {
        "total": len(rows),
        "answered": outcomes.get("answered", 0),
        "refused": outcomes.get("refused", 0),
        "general_guidance": outcomes.get("general_guidance", 0),
        "low_confidence_answered": outcomes.get("low_confidence_answered", 0),
        "by_domain": by_domain,
        "refusal_reason_breakdown": dict(refusal_reasons),
        "unexpected_outcomes": unexpected,
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("\n=== Eval Summary ===")
    print(
        f"Total: {summary['total']} | Answered: {summary['answered']} | "
        f"Refused: {summary['refused']} | "
        f"General-guidance: {summary.get('general_guidance', 0)} | "
        f"Low-confidence: {summary['low_confidence_answered']}"
    )
    print("\nBy domain:")
    for domain, info in (summary.get("by_domain") or {}).items():
        parts = [f"{info['answered']}/{info['total']} answered"]
        if info["refused"]:
            reasons = info.get("refusal_reasons") or {}
            reason_s = ", ".join(f"{k}:{v}" for k, v in reasons.items()) or "unknown"
            parts.append(f"{info['refused']} refused (reason: {reason_s})")
        if info.get("general_guidance"):
            parts.append(f"{info['general_guidance']} general_guidance")
        if info["low_confidence_answered"]:
            parts.append(f"{info['low_confidence_answered']} low-confidence")
        avg = info.get("avg_confidence")
        avg_s = f", avg_confidence={avg}" if avg is not None else ""
        print(f"  {domain:10s} {', '.join(parts)}{avg_s}")

    print("\nRefusal reason breakdown:")
    breakdown = summary.get("refusal_reason_breakdown") or {}
    if not breakdown:
        print("  (none)")
    else:
        for reason, n in sorted(breakdown.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {reason}: {n}")

    unexpected = summary.get("unexpected_outcomes") or []
    print(f"\nUnexpected outcomes (mismatch with expected_outcome): {len(unexpected)}")
    for u in unexpected:
        extra = ""
        if u.get("refusal_reason"):
            extra = f" (reason={u['refusal_reason']}"
            if u.get("score") is not None:
                extra += f", score={u['score']}, threshold={u.get('threshold')}"
            extra += ")"
        print(f"  - {u['id']}: expected={u['expected']}, got={u['got']}{extra}")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="questions.jsonl RAG eval harness")
    parser.add_argument(
        "--questions",
        type=Path,
        default=QUESTIONS_PATH,
        help="Path to questions.jsonl",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", type=str, default="", help="Comma-separated question ids")
    parser.add_argument("--domain", type=str, default="")
    parser.add_argument(
        "--via",
        choices=("api", "inprocess"),
        default=os.getenv("EVAL_VIA", "api"),
        help="api=POST /ask (default); inprocess=build_rag_chain",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000"),
        help="Local/staging API base (never production unless --allow-production)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("EVAL_TOKEN", ""),
        help="Bearer JWT for /ask (or set EVAL_TOKEN)",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Allow EVAL_BASE_URL that looks like production",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=float(os.getenv("EVAL_SLEEP_SECONDS", "0.5")),
        help="Pause between questions (rate/cost control)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Results JSON path (default: eval/results/<timestamp>.json)",
    )
    args = parser.parse_args()

    from app.core.config import DEFAULT_TOP_K

    top_k = args.top_k or DEFAULT_TOP_K
    items = load_questions(args.questions)
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [i for i in items if i["id"] in want]
    if args.domain:
        items = [i for i in items if i.get("domain") == args.domain]
    if args.limit is not None:
        items = items[: args.limit]

    if not items:
        print("No questions to run.", file=sys.stderr)
        return 1

    if args.via == "api":
        _assert_safe_base_url(args.base_url, allow_production=args.allow_production)
        if not args.token:
            print(
                "EVAL_TOKEN / --token required for --via api "
                "(or use --via inprocess).",
                file=sys.stderr,
            )
            return 1
        print(f"Eval via API {args.base_url}/ask (n={len(items)})", flush=True)
    else:
        print(
            f"Eval via in-process build_rag_chain (n={len(items)}). "
            "May record OpenAI usage if OPENAI_API_KEY is set.",
            flush=True,
        )

    rows: list[dict] = []
    for item in items:
        qid = item["id"]
        print(f"Running {qid} ({item.get('domain')}) ...", flush=True)
        t0 = time.time()
        try:
            if args.via == "api":
                resp = run_via_api(
                    item["question"],
                    base_url=args.base_url,
                    token=args.token,
                    top_k=top_k,
                )
            else:
                resp = run_via_inprocess(item["question"], top_k=top_k)
        except Exception as e:  # noqa: BLE001
            resp = {
                "answer": str(e),
                "is_error": True,
                "error_code": 500,
                "sources": [],
                "refusal_reason": "pipeline_error",
            }

        query_id = resp.get("query_id") if isinstance(resp, dict) else None
        # Give JSONL writer a moment on slow FS
        time.sleep(0.05)
        trace = _load_trace_by_query_id(query_id)
        gen = (trace or {}).get("generate") or {}
        outcome = _infer_outcome_from_response(
            resp if isinstance(resp, dict) else {}, trace
        )
        refusal = None
        if isinstance(resp, dict):
            refusal = resp.get("refusal_reason") or gen.get("refusal_reason")
        if outcome != "refused":
            # Keep reason only for refusals in summary; still store in row
            pass

        contains_ok = None
        needles = item.get("expected_answer_contains") or []
        answer = (resp.get("answer") or "") if isinstance(resp, dict) else ""
        if needles and outcome in {"answered", "low_confidence_answered"}:
            contains_ok = all(n in answer for n in needles)

        row = {
            "id": qid,
            "domain": item.get("domain"),
            "question": item.get("question"),
            "expected_outcome": item.get("expected_outcome"),
            "expected_outcomes": item.get("expected_outcomes"),
            "expected_min_confidence": item.get("expected_min_confidence"),
            "expected_answer_contains": needles,
            "actual_outcome": outcome,
            "refusal_reason": refusal,
            "query_id": query_id,
            "final_confidence_score": gen.get("final_confidence_score")
            if gen
            else (resp.get("citation_accuracy") if isinstance(resp, dict) else None),
            "confidence_threshold": gen.get("confidence_threshold"),
            "answer_contains_ok": contains_ok,
            "elapsed_s": round(time.time() - t0, 3),
            "response": {
                k: resp.get(k)
                for k in (
                    "answer",
                    "sources",
                    "no_context",
                    "grounded",
                    "citation_confidence",
                    "citation_accuracy",
                    "domain",
                    "domain_confidence",
                    "is_error",
                    "error_code",
                    "refusal_reason",
                    "query_id",
                    "response_type",
                )
                if isinstance(resp, dict) and k in resp
            },
            "trace": trace,
        }
        rows.append(row)
        if args.sleep > 0:
            time.sleep(args.sleep)

    summary = summarize(rows)
    print_summary(summary)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out or (RESULTS_DIR / f"{ts}.json")
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "via": args.via,
        "base_url": args.base_url if args.via == "api" else None,
        "questions_path": str(args.questions),
        "n": len(rows),
        "summary": summary,
        "results": rows,
        "note": (
            "Placeholder questions until replaced with real production samples. "
            "Compare refusal_reason breakdown before changing thresholds/corpus."
        ),
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nResults saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
