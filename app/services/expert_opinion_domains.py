"""Domains where a fixed legal answer is insufficient — expert opinion is required.

Used by eval set ``expert_domain_id`` and (later) RAG response flags.
This module does not call the LLM; it is a registry + matcher only.
"""

from __future__ import annotations

from typing import Any

# Living registry: id → human-readable description + cue phrases for heuristics.
EXPERT_OPINION_DOMAINS: dict[str, dict[str, Any]] = {
    "fault_percentage_accident": {
        "label": "درصد تقصیر در حوادث کار / ساختمانی",
        "cues": [
            "چند درصد مقصر",
            "درصد تقصیر",
            "تقصیر کارفرما",
            "تقصیر مالک",
            "سقوط",
            "حادثه ناشی از کار",
        ],
    },
    "civil_damages_quantum": {
        "label": "میزان خسارت مدنی قابل مطالبه",
        "cues": ["چقدر خسارت", "میزان خسارت", "محاسبه خسارت"],
    },
    "diya_complex_injury": {
        "label": "دیه جراحات پیچیده / چندگانه",
        "cues": ["دیه", "ارش", "ضربه مغزی", "ازکارافتادگی"],
    },
    "labor_contract_scope_liability": {
        "label": "تفکیک مسئولیت پیمانکار جزء و مالک/کارفرما",
        "cues": ["پیمانکار جزء", "محدوده قرارداد", "فقط مسئول اجرا"],
    },
    "medical_malpractice_share": {
        "label": "سهم تقصیر در قصور پزشکی",
        "cues": ["قصور پزشکی", "درصد تقصیر پزشک"],
    },
}


def match_expert_domain(question: str) -> str | None:
    """Return best-matching expert_domain_id or None."""
    q = (question or "").replace("\u200c", " ")
    best_id = None
    best_score = 0
    for domain_id, meta in EXPERT_OPINION_DOMAINS.items():
        score = sum(1 for cue in meta.get("cues") or [] if cue in q)
        if score > best_score:
            best_score = score
            best_id = domain_id
    return best_id if best_score > 0 else None
