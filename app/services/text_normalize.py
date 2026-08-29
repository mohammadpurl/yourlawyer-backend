"""Shared Persian text normalization for ingest and query embedding paths."""

from __future__ import annotations

import unicodedata


def normalize_persian_text(text: str) -> str:
    """NFKC + Arabic/Persian yeh/kaf unify; keep ZWNJ; strip BOM.

    Used before E5 passage/query embedding so corpus and questions align.
    Safe and idempotent for already-normalized text.
    """
    if not text:
        return ""
    # NFKC: presentation forms → standard letters (e.g. ﻗﺎﻧﻮن → قانون)
    t = unicodedata.normalize("NFKC", text)
    # Keep ZWNJ explicitly (no-op replace documents intent)
    t = t.replace("\u200c", "\u200c")
    t = t.replace("ي", "ی").replace("ك", "ک")
    t = t.replace("\ufeff", "")
    return t
