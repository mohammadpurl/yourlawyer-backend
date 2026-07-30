"""Direct test of embedding model diversity."""
from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.core.config import EMBEDDING_MODEL, LOCAL_EMBEDDING_MODEL_DIR, HF_HOME
from app.services.vectorstore import get_embeddings

OUT = "storage/_model_test.txt"
lines: list[str] = []
lines.append(f"EMBEDDING_MODEL={EMBEDDING_MODEL}")
lines.append(f"LOCAL_DIR={LOCAL_EMBEDDING_MODEL_DIR} exists={LOCAL_EMBEDDING_MODEL_DIR.is_dir()}")
lines.append(f"HF_HOME={HF_HOME}")

emb = get_embeddings()
texts = [
    "query: شرایط طلاق توافقی چیست",
    "query: hello world test",
    "query: قانون کار ایران",
    "passage: ماده 1133 قانون مدنی",
    "passage: بند 4 از بخشنامه آموزش و پرورش",
    "",
    "a",
]
vecs = []
for t in texts:
    if hasattr(emb, "embed_query") and t.startswith("query:"):
        v = np.asarray(emb.embed_query(t), dtype=np.float64)
    else:
        v = np.asarray(emb.embed_documents([t])[0], dtype=np.float64)
    vecs.append(v)
    lines.append(f"text={t[:50]!r} norm={np.linalg.norm(v):.4f} first3={v[:3].tolist()}")

# pairwise
lines.append("=== pairwise cos ===")
for i in range(len(texts)):
    for j in range(i + 1, len(texts)):
        cos = float(vecs[i] @ vecs[j])
        lines.append(f"{i}vs{j} cos={cos:.6f}")

# Direct SentenceTransformer
lines.append("=== direct SentenceTransformer ===")
try:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(EMBEDDING_MODEL))
    st_vecs = model.encode(
        ["query: طلاق", "query: hello", "passage: ماده مدنی"],
        normalize_embeddings=True,
    )
    st_vecs = np.asarray(st_vecs, dtype=np.float64)
    lines.append(f"st 0vs1={float(st_vecs[0] @ st_vecs[1]):.6f}")
    lines.append(f"st 0vs2={float(st_vecs[0] @ st_vecs[2]):.6f}")
    lines.append(f"st 1vs2={float(st_vecs[1] @ st_vecs[2]):.6f}")
except Exception as e:
    lines.append(f"ST ERR {type(e).__name__}: {e}")

open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("wrote", OUT)
