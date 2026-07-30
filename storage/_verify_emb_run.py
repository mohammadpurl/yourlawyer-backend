"""Verify stored vs recompute embeddings for identical-cos docs."""
from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.services.vectorstore import get_vectorstore

OUT = "storage/_verify_emb.txt"
lines: list[str] = []

vs = get_vectorstore()
col = vs._collection
emb_fn = vs._embedding_function

q_text = "query: شرایط طلاق توافقی چیست"
q = np.asarray(emb_fn.embed_query(q_text), dtype=np.float64)

# Find a few docs that have cos~1 with query via get
batch = col.get(limit=2000, offset=0, include=["embeddings", "documents", "metadatas"])
embs = np.asarray(batch.get("embeddings"), dtype=np.float64)
docs = batch.get("documents") or []
metas = batch.get("metadatas") or []
ids = batch.get("ids") or []
sims = embs @ q
perfect = np.where(sims > 0.999)[0]
lines.append(f"in first 2000: perfect_match_count={len(perfect)}")

for i in perfect[:5]:
    text = docs[i] or ""
    stored = embs[i]
    # Re-embed the stored document text as-is
    recomputed = np.asarray(emb_fn.embed_documents([text])[0], dtype=np.float64)
    # Also try without passage prefix / with
    text_noprefix = text[len("passage: ") :] if text.startswith("passage: ") else text
    re_passage = np.asarray(
        emb_fn.embed_documents([text if text.startswith("passage:") else f"passage: {text}"])[0],
        dtype=np.float64,
    )
    re_raw = np.asarray(emb_fn.embed_documents([text_noprefix])[0], dtype=np.float64)

    lines.append(f"--- id={ids[i]} src={(metas[i] or {}).get('source','')[:70]}")
    lines.append(f"text_head={text[:80]!r}")
    lines.append(f"stored·q={float(stored @ q):.6f}")
    lines.append(f"recomputed_as_stored_text·q={float(recomputed @ q):.6f}")
    lines.append(f"recomputed_as_stored_text·stored={float(recomputed @ stored):.6f}")
    lines.append(f"re_passage·stored={float(re_passage @ stored):.6f}")
    lines.append(f"re_raw·stored={float(re_raw @ stored):.6f}")
    lines.append(f"stored==q? {np.allclose(stored, q)}")
    lines.append(f"all_perfect_same_as_each_other? check next")

if len(perfect) >= 2:
    a, b = embs[perfect[0]], embs[perfect[1]]
    lines.append(f"perfect0==perfect1? {np.allclose(a, b)} cos={float(a @ b):.6f}")
    lines.append(f"perfect0==q? {np.allclose(a, q)}")

# How many of first 20k equal q exactly?
n_eq = 0
n_total = 0
unique_vecs = {}
for offset in range(0, 20000, 2000):
    b = col.get(limit=2000, offset=offset, include=["embeddings"])
    e = np.asarray(b.get("embeddings"), dtype=np.float64)
    n_total += len(e)
    n_eq += int(np.sum(np.abs(e @ q - 1.0) < 1e-5))
    for row in e:
        key = tuple(np.round(row, 5))
        unique_vecs[key] = unique_vecs.get(key, 0) + 1

top_dupes = sorted(unique_vecs.items(), key=lambda x: -x[1])[:5]
lines.append(f"in {n_total} docs: exact_eq_to_current_query={n_eq}")
lines.append("top duplicate embedding frequencies:")
for key, cnt in top_dupes:
    vec = np.asarray(key, dtype=np.float64)
    # renorm approx
    lines.append(f"  count={cnt} cos_with_q={float(vec @ q):.4f}")

# Check if duplicate vector equals SOME other query embedding
other_q = np.asarray(emb_fn.embed_query("query: hello world test"), dtype=np.float64)
lines.append(f"other_q cos with q={float(other_q @ q):.4f}")
# how many equal other_q?
n_other = 0
for offset in range(0, 4000, 2000):
    b = col.get(limit=2000, offset=offset, include=["embeddings"])
    e = np.asarray(b.get("embeddings"), dtype=np.float64)
    n_other += int(np.sum(np.abs(e @ other_q - 1.0) < 1e-5))
lines.append(f"in first 4000: exact_eq_to_hello_query={n_other}")

open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("wrote", OUT)
