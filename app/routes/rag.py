from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.config import UPLOAD_DIRECTORY, DEFAULT_TOP_K
from app.core.security import encrypt_bytes, is_encryption_enabled
from app.services.ingestion import ingest_files
from app.services.vectorstore import add_documents, stats
from app.services.rag import build_rag_chain
from app.schemas.rag import AskRequest, AskResponse


router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/stats")
def get_stats():
    return stats()


@router.post("/upload")
async def upload(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    saved_paths: List[Path] = []
    encryption_active = is_encryption_enabled()

    for f in files:
        original_dest = UPLOAD_DIRECTORY / f.filename
        content = await f.read()
        original_dest.parent.mkdir(parents=True, exist_ok=True)

        if encryption_active:
            dest = original_dest.with_suffix(original_dest.suffix + ".enc")
            dest.write_bytes(encrypt_bytes(content))
        else:
            dest = original_dest
            dest.write_bytes(content)

        saved_paths.append(dest)
    docs = ingest_files(saved_paths)
    added = add_documents(docs)
    return {"uploaded": len(files), "chunks_added": added}


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    k = req.top_k or DEFAULT_TOP_K
    use_enhanced = (
        req.use_enhanced_retrieval if req.use_enhanced_retrieval is not None else True
    )
    rag = build_rag_chain(k=k, use_enhanced_retrieval=use_enhanced)
    result = rag(req.question)
    return AskResponse(**result)


@router.delete("/reset")
def reset_collection(collection_name: str = "legal-texts"):
    """Reset/delete a ChromaDB collection (useful for fixing corruption)."""
    import logging

    logger = logging.getLogger(__name__)

    try:
        import chromadb
        from app.core.config import PERSIST_DIRECTORY

        client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)
        try:
            client.delete_collection(collection_name)
            logger.info(f"Deleted collection: {collection_name}")
            return {
                "status": "success",
                "message": f"Collection '{collection_name}' deleted successfully",
            }
        except Exception as e:
            logger.warning(f"Could not delete collection: {e}")
            return {
                "status": "error",
                "message": f"Collection '{collection_name}' may not exist: {e}",
            }
    except Exception as e:
        logger.error(f"Error resetting collection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset collection: {e}")
