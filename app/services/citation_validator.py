"""Citation grounding validation against retrieved RAG chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

_DIGIT_TRANS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)

_PERSIAN_ORDINALS = {
    "اول": "1",
    "یکم": "1",
    "دوم": "2",
    "سوم": "3",
    "چهارم": "4",
    "پنجم": "5",
    "ششم": "6",
    "هفتم": "7",
    "هشتم": "8",
    "نهم": "9",
    "دهم": "10",
    "یازدهم": "11",
    "دوازدهم": "12",
    "سیزدهم": "13",
    "چهاردهم": "14",
    "پانزدهم": "15",
    "شانزدهم": "16",
    "هفدهم": "17",
    "هجدهم": "18",
    "نوزدهم": "19",
    "بیستم": "20",
}

# ماده ۱۰ / ماده 10 / ماده دهم / تبصره ۲ ماده ۱۵
_CITATION_RE = re.compile(
    r"(?:"
    r"تبصره\s+(?P<note>[\d۰-۹٠-٩]+|[\u0600-\u06FF]+)"
    r"(?:\s+ماده\s+(?P<article_of_note>[\d۰-۹٠-٩]+|[\u0600-\u06FF]+))?"
    r"|"
    r"ماده\s+(?P<article>[\d۰-۹٠-٩]+|[\u0600-\u06FF]+)"
    r"|"
    r"اصل\s+(?P<principle>[\d۰-۹٠-٩]+|[\u0600-\u06FF]+)"
    r")"
)


@dataclass
class CitationCheckResult:
    is_valid: bool
    cited_articles: list[str]
    unverified_citations: list[str]
    confidence_flag: str  # verified | partial | unverified


def normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_TRANS)


def _normalize_token(token: str) -> str:
    token = normalize_digits(token.strip())
    if token in _PERSIAN_ORDINALS:
        return _PERSIAN_ORDINALS[token]
    return token


def _canonical_form(match: re.Match) -> str:
    if match.group("note"):
        note = _normalize_token(match.group("note"))
        article = match.group("article_of_note")
        if article:
            return f"تبصره {note} ماده {_normalize_token(article)}"
        return f"تبصره {note}"
    if match.group("article"):
        return f"ماده {_normalize_token(match.group('article'))}"
    if match.group("principle"):
        return f"اصل {_normalize_token(match.group('principle'))}"
    return match.group(0)


def extract_citations(response_text: str) -> list[str]:
    """Extract Persian legal citation phrases; return display forms (original span)."""
    if not response_text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _CITATION_RE.finditer(response_text):
        raw = match.group(0)
        key = _canonical_form(match)
        if key in seen:
            continue
        seen.add(key)
        found.append(raw)
    return found


def _context_has_citation(canonical: str, context_norm: str) -> bool:
    """Loose containment: require the number + keyword to appear near each other."""
    # canonical like "ماده 10" or "تبصره 2 ماده 15"
    parts = canonical.split()
    if not parts:
        return False
    # Simple: all numeric tokens and at least the primary keyword must appear
    if canonical.replace(" ", "") in context_norm.replace(" ", ""):
        return True
    # Fallback: keyword + number both in context
    if "تبصره" in canonical:
        note_nums = re.findall(r"\d+", canonical)
        if not note_nums:
            return False
        # Prefer "تبصره N" substring
        needle = f"تبصره {note_nums[0]}"
        if needle in context_norm:
            if len(note_nums) > 1:
                return f"ماده {note_nums[1]}" in context_norm
            return True
        return False
    if "اصل" in canonical:
        nums = re.findall(r"\d+", canonical)
        return bool(nums) and f"اصل {nums[0]}" in context_norm
    nums = re.findall(r"\d+", canonical)
    return bool(nums) and f"ماده {nums[0]}" in context_norm


def validate_citations(
    response_text: str,
    retrieved_chunks: Sequence[str] | Iterable[str],
) -> CitationCheckResult:
    """
    Compare extracted citations against retrieved chunk text.
    Unverified citations likely indicate hallucination.
    """
    cited_raw = extract_citations(response_text)
    chunks = list(retrieved_chunks)
    combined = normalize_digits(" ".join(chunks or []))

    unverified: list[str] = []
    for raw in cited_raw:
        match = _CITATION_RE.search(raw)
        if not match:
            unverified.append(raw)
            continue
        canonical = _canonical_form(match)
        if not _context_has_citation(canonical, combined):
            unverified.append(raw)

    if not cited_raw:
        confidence = "unverified"
    elif not unverified:
        confidence = "verified"
    else:
        confidence = "partial"

    return CitationCheckResult(
        is_valid=len(unverified) == 0 and bool(cited_raw),
        cited_articles=cited_raw,
        unverified_citations=unverified,
        confidence_flag=confidence,
    )


def citation_accuracy_score(result: CitationCheckResult) -> float:
    if result.confidence_flag == "verified":
        return 1.0
    if result.confidence_flag == "partial":
        total = len(result.cited_articles) or 1
        ok = total - len(result.unverified_citations)
        return round(max(0.0, ok / total), 2)
    return 0.0
