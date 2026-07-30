"""Deep debug of why E5 collapses after full download."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

OUT = "storage/_e5_deep.txt"
lines: list[str] = []

snap = Path(
    "storage/huggingface/hub/models--intfloat--multilingual-e5-base/"
    "snapshots/d128750597153bb5987e10b1c3493a34e5a4502a"
)
ms = snap / "model.safetensors"
lines.append(f"safetensors exists={ms.exists()} resolve={ms.resolve()} size={ms.stat().st_size}")

# safetensors header sanity
try:
    from safetensors import safe_open

    with safe_open(str(ms), framework="pt") as f:
        keys = list(f.keys())
        lines.append(f"n_tensors={len(keys)}")
        w = f.get_tensor("embeddings.word_embeddings.weight")
        lines.append(
            f"word_emb shape={tuple(w.shape)} mean={float(w.float().mean()):.6f} "
            f"std={float(w.float().std()):.6f}"
        )
        # compare two token rows
        r0 = w[100].float()
        r1 = w[5000].float()
        lines.append(f"token100vs5000 cos={float(torch.nn.functional.cosine_similarity(r0, r1, dim=0)):.4f}")
except Exception as e:
    lines.append(f"safetensors ERR {type(e).__name__}: {e}")

from sentence_transformers import SentenceTransformer

# Load from local snapshot path explicitly
model = SentenceTransformer(str(snap.resolve()))
lines.append(f"loaded local snap")

texts = ["query: طلاق", "query: hello", "passage: قانون مدنی"]
with torch.no_grad():
    feats = model.tokenize(texts)
    lines.append(f"input_ids=\n{feats['input_ids']}")
    # transformer output
    out = model[0](feats)
    tok_emb = out["token_embeddings"]
    lines.append(f"token_embeddings shape={tuple(tok_emb.shape)}")
    # Are token embeddings different across batch?
    for i in range(len(texts)):
        te = tok_emb[i]
        lines.append(
            f"batch{i} tok0={te[0,:3].tolist()} mean={float(te.mean()):.6f} "
            f"std={float(te.std()):.6f}"
        )
    # sentence embeddings via full encode
    emb = model.encode(texts, normalize_embeddings=True)
    emb = np.asarray(emb)
    lines.append(f"encode 0vs1={float(emb[0]@emb[1]):.6f} 0vs2={float(emb[0]@emb[2]):.6f}")

# Also try transformers AutoModel directly
try:
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(snap))
    mdl = AutoModel.from_pretrained(str(snap))
    mdl.eval()
    batch = tok(texts, padding=True, truncation=True, return_tensors="pt")
    with torch.no_grad():
        hs = mdl(**batch).last_hidden_state
    lines.append(f"AutoModel hidden shape={tuple(hs.shape)}")
    for i in range(len(texts)):
        lines.append(f"AutoModel b{i} mean={float(hs[i].mean()):.6f} std={float(hs[i].std()):.6f} first={hs[i,0,:3].tolist()}")
    # mean pool
    mask = batch["attention_mask"].unsqueeze(-1)
    summed = (hs * mask).sum(1)
    counts = mask.sum(1).clamp(min=1)
    pooled = summed / counts
    pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
    lines.append(
        f"AutoModel pooled 0vs1={float((pooled[0]*pooled[1]).sum()):.6f} "
        f"0vs2={float((pooled[0]*pooled[2]).sum()):.6f}"
    )
except Exception as e:
    lines.append(f"AutoModel ERR {type(e).__name__}: {e}")

open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("wrote", OUT)
