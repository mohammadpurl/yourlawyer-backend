"""Check if top-hit embeddings are broken (zeros / identical)."""
from __future__ import annotations

import math
import os

import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.services.vectorstore import get_vectorstore

OUT = "storage/_embed_broken.txt"
lines: list[str] = []

vs = get_vectorstore()
col = vs._collection
emb_fn = vs._embedding_function

q = np.asarray(emb_fn.embed_query("query: شرایط طلاق توافقی چیست"), dtype=np.float64)
lines.append(f"q_norm={np.linalg.norm(q):.6f}")

res = col.query(
    query_embeddings=[q.tolist()],
    n_results=5,
    include=["documents", "metadatas", "distances", "embeddings"],
)
dists = (res.get("distances") or [[]])[0]
metas = (res.get("metadatas") or [[]])[0]
docs = (res.get("documents") or [[]])[0]
embs = (res.get("embeddings") or [[]])[0]

lines.append(f"n_results embeddings type={type(embs)} len={len(embs) if embs is not None else None}")

arr = np.asarray(embs, dtype=np.float64) if embs is not None else None
if arr is not None and arr.size:
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    lines.append(f"top_embs_shape={arr.shape}")
    for i in range(len(arr)):
        e = arr[i]
        en = float(np.linalg.norm(e))
        cos = float(np.dot(q, e) / (np.linalg.norm(q) * en + 1e-12))
        l2 = float(np.linalg.norm(q - e))
        zero_frac = float(np.mean(np.abs(e) < 1e-12))
        lines.append(
            f"i={i} dist_reported={dists[i]:.8f} emb_norm={en:.6f} "
            f"cos={cos:.6f} l2={l2:.6f} zero_frac={zero_frac:.3f} "
            f"src={(metas[i] or {}).get('source','')[:70]}"
        )
        lines.append(f"  text={(docs[i] or '')[:90].replace(chr(10),' ')}")
else:
    lines.append("NO embeddings returned from query — fetching by id")
    ids = (res.get("ids") or [[]])[0]
    lines.append(f"ids={ids}")
    got = col.get(ids=ids, include=["embeddings", "documents", "metadatas"])
    e2 = np.asarray(got.get("embeddings"), dtype=np.float64)
    lines.append(f"got_shape={e2.shape}")
    for i in range(len(e2)):
        e = e2[i]
        en = float(np.linalg.norm(e))
        cos = float(np.dot(q, e) / (np.linalg.norm(q) * en + 1e-12))
        lines.append(f"i={i} norm={en:.6f} cos={cos:.6f} first5={e[:5].tolist()}")

# Sample random 200 embeddings: how many near-zero / identical?
sample_n = 500
got = col.get(limit=sample_n, include=["embeddings"])
e_all = np.asarray(got.get("embeddings"), dtype=np.float64)
norms = np.linalg.norm(e_all, axis=1)
near_zero = int(np.sum(norms < 1e-6))
unique_approx = len({tuple(np.round(e, 4)) for e in e_all[:100]})
lines.append(
    f"sample_n={sample_n} near_zero_norm={near_zero} "
    f"norm_min={norms.min():.6f} norm_max={norms.max():.6f} norm_mean={norms.mean():.6f}"
)
lines.append(f"unique_among_first_100_rounded4={unique_approx}")

# Check collection metadata (hnsw space)
try:
    lines.append(f"collection_metadata={col.metadata}")
except Exception as e:
    lines.append(f"meta err {e}")

# Brute-force top-5 cosine over a larger sample for طلاق docs
needle = "طلاق توافقی"
# also search civil code articles about divorce
hits = []
offset = 0
batch = 3000
scanned = 0
max_scan = 60000
best = []  # (cos, src, snip)
while offset < min(col.count(), max_scan):
    batch_data = col.get(
        limit=min(batch, col.count() - offset),
        offset=offset,
        include=["embeddings", "documents", "metadatas"],
    )
    embs_b = np.asarray(batch_data.get("embeddings"), dtype=np.float64)
    docs_b = batch_data.get("documents") or []
    metas_b = batch_data.get("metadatas") or []
    if embs_b.size == 0:
        break
    # cosine sim
    sims = embs_b @ q  # both normalized
    for i, sim in enumerate(sims):
        text = docs_b[i] or ""
        src = str((metas_b[i] or {}).get("source", ""))
        if "طلاق" in text or "مدني" in src or "مدنی" in src:
            best.append((float(sim), src[:80], text[:100].replace("\n", " ")))
        # track global best too
        hits.append((float(sim), src[:80], text[:80].replace("\n", " ")))
    scanned += len(docs_b)
    offset += batch
    # keep top hits memory bounded
    hits = sorted(hits, key=lambda x: -x[0])[:20]
    best = sorted(best, key=lambda x: -x[0])[:20]

lines.append(f"=== brute force over {scanned} docs ===")
lines.append("--- global top by cosine ---")
for sim, src, snip in hits[:8]:
    lines.append(f"cos={sim:.4f} | {src} | {snip}")
lines.append("--- best among طلاق/مدنی ---")
for sim, src, snip in best[:8]:
    lines.append(f"cos={sim:.4f} | {src} | {snip}")

open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("wrote", OUT)
