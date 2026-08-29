"""In-memory BM25 keyword index over the Chroma legal-texts corpus.

Why this exists (2026-08-23): dense E5 embedding search alone was confirmed
to miss exact-term legal queries entirely. For the query "هبه چه تعریفی در
قانون مدنی دارد؟", the chunk containing ماده ۷۹۸ (the actual هبه article)
did not appear even in the top-200 dense results out of ~179k chunks, despite
existing verbatim in the corpus. BM25 keyword overlap finds it immediately
because "هبه" is a rare, distinctive token. Used as a second retrieval path
whose results are unioned with dense hits before reranking — see
``app/services/enhanced_retrieval.py``.

The index is built once per process (lazy singleton) directly from the Chroma
collection and kept in memory. It is NOT persisted to disk; a process restart
rebuilds it from Chroma, which stays the single source of truth.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import List, Optional

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from app.services.text_normalize import normalize_persian_text

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# High-frequency Persian function words. Left unfiltered, BM25 lets their
# cumulative (small but nonzero) per-token score outweigh the one truly
# distinctive legal term in a query — confirmed empirically: without this
# filter, the query "هبه چه تعریفی در قانون مدنی دارد؟" ranked the correct
# ماده ۷۹۸ chunk at #665 (buried under docs matching only "چه/در/قانون/مدنی/دارد").
_STOPWORDS = frozenset(
    """
    چه در به از را با که این آن است هست باشد بود برای یا و تا ها های
    دارد داشت دارند شود شد شوند می نمی بر یک همه هر نیز آیا کدام چرا
    چطور چگونه کند کنند کرد کردن کنم چند چقدر اگر ولی اما همچنین حتی
    """.split()
)

_lock = threading.Lock()
_bm25: Optional[BM25Okapi] = None
_corpus_ids: List[str] = []
_corpus_documents: List[str] = []
_corpus_metadatas: List[dict] = []


def _strip_embed_prefix(text: str) -> str:
    t = text or ""
    for prefix in ("passage: ", "query: ", "passage:", "query:"):
        if t.startswith(prefix):
            return t[len(prefix):].lstrip()
    return t


def _tokenize(text: str) -> List[str]:
    t = normalize_persian_text(_strip_embed_prefix(text or ""))
    return [
        tok
        for tok in _TOKEN_RE.findall(t)
        if len(tok) > 1 and tok not in _STOPWORDS
    ]


def _build_index() -> None:
    global _bm25, _corpus_ids, _corpus_documents, _corpus_metadatas

    from app.services.vectorstore import get_vectorstore
    from app.core.config import CHROMA_COLLECTION

    col = get_vectorstore(CHROMA_COLLECTION)._collection
    total = col.count()
    logger.info("Building BM25 index over %s chunks (one-time, in-memory)...", total)

    data = col.get(include=["documents", "metadatas"], limit=total)
    ids = data.get("ids") or []
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []

    tokenized_corpus = [_tokenize(d) for d in documents]
    bm25 = BM25Okapi(tokenized_corpus)

    _corpus_ids = ids
    _corpus_documents = documents
    _corpus_metadatas = metadatas
    _bm25 = bm25
    logger.info("BM25 index built: %s chunks indexed.", len(documents))


def _ensure_index() -> None:
    if _bm25 is not None:
        return
    with _lock:
        if _bm25 is None:
            _build_index()


def bm25_search(query: str, k: int = 8) -> List[Document]:
    """Keyword search over the full corpus. Returns [] if no term overlap at all."""
    if not (query or "").strip():
        return []
    try:
        _ensure_index()
    except Exception as e:
        logger.warning("BM25 index build failed, skipping keyword retrieval: %s", e)
        return []
    if _bm25 is None:
        return []

    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    scores = _bm25.get_scores(q_tokens)
    # argsort descending, keep only positive-score (real term overlap) hits
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    docs: List[Document] = []
    for i in ranked[: max(1, k * 3)]:  # oversample a bit before score-cutoff
        if scores[i] <= 0:
            break
        docs.append(
            Document(
                page_content=_corpus_documents[i],
                metadata=dict(_corpus_metadatas[i] or {}),
            )
        )
        if len(docs) >= k:
            break
    return docs
