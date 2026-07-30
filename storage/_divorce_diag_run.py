"""One-off divorce retrieval diagnostic."""
from __future__ import annotations

import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.services.vectorstore import get_vectorstore
from app.services.enhanced_retrieval import EnhancedRetriever

OUT = "storage/_divorce_diag.txt"
lines: list[str] = []

vs = get_vectorstore()
q = "شرایط طلاق توافقی چیست"

for label, query in [
    ("query_prefixed", "query: " + q),
    ("raw", q),
    ("query_talagh", "query: طلاق توافقی شرایط"),
]:
    lines.append(f"=== {label}: {query!r} ===")
    try:
        pairs = vs.similarity_search_with_score(query, k=8)
        for d, s in pairs:
            src = (d.metadata or {}).get("source", "")[:100]
            snip = (d.page_content or "")[:100].replace("\n", " ")
            lines.append(f"score={s:.4f} | {src} | {snip}")
    except Exception as e:
        lines.append(f"ERR {type(e).__name__}: {e}")

# Use collection from the same Chroma instance
try:
    col = vs._collection  # type: ignore[attr-defined]
    for needle in ["طلاق", "طلاق توافقی", "مدنی", "خانواده"]:
        try:
            r = col.get(
                where_document={"$contains": needle},
                limit=5,
                include=["documents", "metadatas"],
            )
            ids = r.get("ids") or []
            lines.append(f"=== contains {needle!r} count_sample={len(ids)} ===")
            for m, doc in zip(r.get("metadatas") or [], r.get("documents") or []):
                lines.append(
                    f"{str((m or {}).get('source', ''))[:100]} | "
                    f"{(doc or '')[:90].replace(chr(10), ' ')}"
                )
        except Exception as e:
            lines.append(f"contains {needle} ERR {type(e).__name__}: {e}")
except Exception as e:
    lines.append(f"collection ERR {type(e).__name__}: {e}")

r = EnhancedRetriever(enable_domain_filter=False)
docs = r.retrieve(q, k=5)
lines.append("=== enhanced ===")
for d in docs:
    lines.append(str((d.metadata or {}).get("source", ""))[:120])

open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("wrote", OUT, "lines", len(lines))
