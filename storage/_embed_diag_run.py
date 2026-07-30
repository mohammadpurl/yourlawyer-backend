"""Deeper embedding / corpus diagnostic."""
from __future__ import annotations

import math
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.services.vectorstore import get_vectorstore

OUT = "storage/_embed_diag.txt"
lines: list[str] = []

vs = get_vectorstore()
col = vs._collection
emb_fn = vs._embedding_function

q_text = "query: شرایط طلاق توافقی چیست"
q = emb_fn.embed_query(q_text)
qn = math.sqrt(sum(x * x for x in q))
lines.append(f"query_dim={len(q)} norm={qn:.4f} first3={q[:3]}")

peek = col.get(limit=3, include=["embeddings", "documents", "metadatas"])
embs = peek.get("embeddings")
docs = peek.get("documents") or []
metas = peek.get("metadatas") or []
lines.append(f"count={col.count()}")

if embs is None:
    lines.append("embeddings=None from get — try query include")
else:
    # chromadb may return numpy
    try:
        import numpy as np

        arr = np.asarray(embs)
        lines.append(f"embs_shape={arr.shape}")
        for i in range(min(3, len(arr))):
            e = arr[i]
            en = float(np.linalg.norm(e))
            # cosine distance = 1 - cos_sim for normalized
            cos = float(np.dot(q, e) / (qn * en + 1e-12))
            lines.append(
                f"doc{i} dim={len(e)} norm={en:.4f} cos_sim={cos:.4f} "
                f"src={(metas[i] or {}).get('source','')[:60]} "
                f"text={(docs[i] or '')[:60]!r}"
            )
    except Exception as e:
        lines.append(f"emb parse err {type(e).__name__}: {e}")

# Manual top-k via collection.query
try:
    res = col.query(query_embeddings=[q], n_results=5, include=["documents", "metadatas", "distances"])
    lines.append("=== col.query distances ===")
    for dist, meta, doc in zip(
        (res.get("distances") or [[]])[0],
        (res.get("metadatas") or [[]])[0],
        (res.get("documents") or [[]])[0],
    ):
        lines.append(
            f"dist={dist:.6f} | {(meta or {}).get('source','')[:80]} | "
            f"{(doc or '')[:70].replace(chr(10), ' ')}"
        )
except Exception as e:
    lines.append(f"col.query ERR {type(e).__name__}: {e}")

# Keyword scan sample of corpus for طلاق (batched)
needle = "طلاق"
found = 0
samples = []
batch = 2000
total = col.count()
for offset in range(0, min(total, 40000), batch):
    batch_data = col.get(
        limit=min(batch, total - offset),
        offset=offset,
        include=["documents", "metadatas"],
    )
    for m, d in zip(batch_data.get("metadatas") or [], batch_data.get("documents") or []):
        text = d or ""
        if needle in text:
            found += 1
            if len(samples) < 8:
                idx = text.find(needle)
                snip = text[max(0, idx - 30) : idx + 50].replace("\n", " ")
                samples.append(f"{(m or {}).get('source','')[:70]} | {snip}")
    if offset == 0:
        # also check metadata source names
        pass

lines.append(f"=== scanned first {min(total,40000)} docs, '{needle}' in content: {found} ===")
lines.extend(samples)

# source filename contains طلاق or مدنی
src_hits = 0
src_samples = []
for offset in range(0, min(total, 40000), batch):
    batch_data = col.get(
        limit=min(batch, total - offset),
        offset=offset,
        include=["metadatas"],
    )
    for m in batch_data.get("metadatas") or []:
        src = str((m or {}).get("source", ""))
        if "طلاق" in src or "مدني" in src or "مدنی" in src or "خانواده" in src:
            src_hits += 1
            if len(src_samples) < 10:
                src_samples.append(src[:120])

lines.append(f"=== source name hits (طلاق/مدنی/خانواده) in first 40k: {src_hits} ===")
lines.extend(src_samples)

open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("wrote", OUT)
