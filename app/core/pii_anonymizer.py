"""In-memory PII anonymization for Persian legal queries.

Mappings live only for the duration of a single anonymize→restore cycle and
must never be logged or persisted.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_DIGIT_TRANS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)


class PIIType(str, Enum):
    NATIONAL_ID = "national_id"
    PHONE = "phone"
    NAME = "name"
    ADDRESS = "address"
    CASE_NUMBER = "case_number"


@dataclass(frozen=True)
class PIIMapping:
    placeholder: str
    original_value: str
    pii_type: PIIType
    start_pos: int
    end_pos: int


_PLACEHOLDER_PREFIX = {
    PIIType.NATIONAL_ID: "PII_NATIONAL_ID",
    PIIType.PHONE: "PII_PHONE",
    PIIType.NAME: "PII_NAME",
    PIIType.ADDRESS: "PII_ADDRESS",
    PIIType.CASE_NUMBER: "PII_CASE_NUMBER",
}

_MOBILE_RE = re.compile(r"(?<!\d)(?:\+98|0098|98|0)?9(?:[\s\-]?\d){9}(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}[\s\-]?\d{3,4}[\s\-]?\d{3,4}(?!\d)")
_NATIONAL_ID_RE = re.compile(r"(?<!\d)[\d۰-۹٠-٩]{3}[\s\-]?[\d۰-۹٠-٩]{3}[\s\-]?[\d۰-۹٠-٩]{4}(?!\d)")
_CASE_NUMBER_RE = re.compile(
    r"(?:"
    r"(?:کلاسه|پرونده|شماره\s*پرونده|شماره\s*نامه)\s*[:：]?\s*"
    r"[\d۰-۹٠-٩/\-]+"
    r"|"
    r"(?<!\d)[\d۰-۹]{2,4}\s*/\s*[\d۰-۹]{3,8}(?!\d)"
    r")"
)
_ADDRESS_RE = re.compile(
    r"(?:"
    r"(?:استان|شهرستان|شهر|محله|خیابان|بلوار|کوچه|بن[\s\-]?بست|"
    r"میدان|پلاک|واحد|طبقه|کدپستی)"
    r"[\u0600-\u06FF\s\d۰-۹٠-٩/\-،,]{4,80}"
    r")"
)
_NAME_TITLE_RE = re.compile(
    r"(?:آقای|خانم|جناب(?:\s+آقای)?|سرکار\s+خانم)\s+"
    r"[\u0600-\u06FF]{2,}(?:\s+[\u0600-\u06FF]{2,}){0,2}"
)

# Used by tests to assert raw PII is gone after anonymize
RAW_NATIONAL_ID_ASSERT_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
RAW_MOBILE_ASSERT_RE = re.compile(r"(?<!\d)(?:\+98|0)?9\d{9}(?!\d)")


def normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_TRANS)


def is_valid_iranian_national_id(value: str) -> bool:
    """Validate Iranian national ID (کد ملی) check digit."""
    digits = normalize_digits(re.sub(r"[\s\-]", "", value))
    if not re.fullmatch(r"\d{10}", digits):
        return False
    if len(set(digits)) == 1:
        return False
    check = int(digits[-1])
    s = sum(int(digits[i]) * (10 - i) for i in range(9)) % 11
    return check == s if s < 2 else check == (11 - s)


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


class PIIAnonymizer:
    """Stateless across requests: each anonymize() keeps counters local."""

    def __init__(self, *, enabled: bool = True, ner_enabled: bool = False) -> None:
        self.enabled = enabled
        self.ner_enabled = ner_enabled
        self._lock = threading.Lock()

    def anonymize(self, text: str) -> Tuple[str, List[PIIMapping]]:
        if not self.enabled or not text:
            return text, []
        counters = {t: 0 for t in PIIType}
        return self._anonymize_with_counters(text, counters)

    def anonymize_many(self, texts: Sequence[str]) -> Tuple[List[str], List[PIIMapping]]:
        """Anonymize multiple strings with one shared placeholder counter."""
        if not self.enabled:
            return list(texts), []
        counters = {t: 0 for t in PIIType}
        results: List[str] = []
        all_mappings: List[PIIMapping] = []
        for text in texts:
            if not text:
                results.append(text)
                continue
            anon, maps = self._anonymize_with_counters(text, counters)
            all_mappings.extend(maps)
            results.append(anon)
        return results, all_mappings

    def restore(self, text: str, mappings: Sequence[PIIMapping]) -> str:
        if not text or not mappings:
            return text
        ordered = sorted(mappings, key=lambda m: len(m.placeholder), reverse=True)
        out = text
        for mapping in ordered:
            out = out.replace(mapping.placeholder, mapping.original_value)
        return out

    def anonymize_for_logging(self, text: str, max_len: int = 200) -> str:
        """Anonymized preview for logs; mappings are discarded immediately."""
        anonymized, mappings = self.anonymize(text or "")
        del mappings
        return anonymized[:max_len]

    def _collect_spans(self, text: str) -> List[Tuple[int, int, PIIType, str]]:
        candidates: List[Tuple[int, int, PIIType, str]] = []

        for match in _NATIONAL_ID_RE.finditer(text):
            raw = match.group(0)
            if is_valid_iranian_national_id(raw):
                candidates.append(
                    (match.start(), match.end(), PIIType.NATIONAL_ID, raw)
                )

        for match in _MOBILE_RE.finditer(text):
            candidates.append(
                (match.start(), match.end(), PIIType.PHONE, match.group(0))
            )

        for match in _LANDLINE_RE.finditer(text):
            raw = match.group(0)
            if any(
                _overlap(match.start(), match.end(), s, e) for s, e, _, _ in candidates
            ):
                continue
            digits_only = re.sub(r"\D", "", normalize_digits(raw))
            if len(digits_only) == 10 and is_valid_iranian_national_id(digits_only):
                continue
            candidates.append((match.start(), match.end(), PIIType.PHONE, raw))

        for match in _CASE_NUMBER_RE.finditer(text):
            candidates.append(
                (match.start(), match.end(), PIIType.CASE_NUMBER, match.group(0))
            )

        for match in _ADDRESS_RE.finditer(text):
            candidates.append(
                (match.start(), match.end(), PIIType.ADDRESS, match.group(0).strip())
            )

        for match in _NAME_TITLE_RE.finditer(text):
            candidates.append(
                (match.start(), match.end(), PIIType.NAME, match.group(0))
            )

        if self.ner_enabled:
            for start, end, value in self._ner_person_spans(text):
                candidates.append((start, end, PIIType.NAME, value))

        candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))
        selected: List[Tuple[int, int, PIIType, str]] = []
        for start, end, pii_type, value in candidates:
            if any(_overlap(start, end, s, e) for s, e, _, _ in selected):
                continue
            selected.append((start, end, pii_type, value))
        selected.sort(key=lambda c: c[0])
        return selected

    def _anonymize_with_counters(
        self, text: str, counters: dict
    ) -> Tuple[str, List[PIIMapping]]:
        selected = self._collect_spans(text)
        mappings: List[PIIMapping] = []
        pieces: List[str] = []
        cursor = 0
        for start, end, pii_type, value in selected:
            pieces.append(text[cursor:start])
            counters[pii_type] = counters.get(pii_type, 0) + 1
            placeholder = f"[{_PLACEHOLDER_PREFIX[pii_type]}_{counters[pii_type]}]"
            pieces.append(placeholder)
            mappings.append(
                PIIMapping(
                    placeholder=placeholder,
                    original_value=value,
                    pii_type=pii_type,
                    start_pos=start,
                    end_pos=end,
                )
            )
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces), mappings

    def _ner_person_spans(self, text: str) -> List[Tuple[int, int, str]]:
        """Optional hazm hook; no-op if hazm is not installed."""
        with self._lock:
            try:
                import hazm  # noqa: F401
            except Exception:
                logger.debug("hazm not installed; NER name detection skipped")
                return []
            # Full sequence NER models are optional; title heuristic already covers
            # common legal phrasing. Extend here when a hazm NER model is configured.
            return []


_default_anonymizer: Optional[PIIAnonymizer] = None
_default_lock = threading.Lock()


def get_pii_anonymizer() -> PIIAnonymizer:
    global _default_anonymizer
    if _default_anonymizer is not None:
        return _default_anonymizer
    with _default_lock:
        if _default_anonymizer is None:
            from app.core.config import PII_ANONYMIZATION_ENABLED, PII_NER_ENABLED

            _default_anonymizer = PIIAnonymizer(
                enabled=PII_ANONYMIZATION_ENABLED,
                ner_enabled=PII_NER_ENABLED,
            )
        return _default_anonymizer


def call_llm_with_pii_protection(invoke_fn, prompt: str, **kwargs):
    """Wrap a sync LLM invoke: anonymize → call → restore (mappings stay local)."""
    anonymizer = get_pii_anonymizer()
    anonymized_prompt, mappings = anonymizer.anonymize(prompt)
    try:
        raw_response = invoke_fn(anonymized_prompt, **kwargs)
    except TypeError:
        raw_response = invoke_fn(anonymized_prompt)
    if not isinstance(raw_response, str):
        return raw_response
    return anonymizer.restore(raw_response, mappings)
