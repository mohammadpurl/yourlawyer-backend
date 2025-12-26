from pathlib import Path
from typing import List
from sqlalchemy.orm import Session
import zipfile
import shutil
import tempfile

from app.core.database import get_db
from app.services.auth import get_current_user
from app.models.user import User, Conversation, Message
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Body
from pydantic import BaseModel

from app.core.config import UPLOAD_DIRECTORY, DEFAULT_TOP_K, BASE_DIR
from app.core.security import encrypt_bytes, is_encryption_enabled
from app.core.rate_limit import limiter, get_rate_limit_string
from app.services.memory import create_memory_from_messages
from fastapi import Request
from app.services.ingestion import ingest_files
from app.services.folder_ingestion import (
    ingest_folder,
    ingest_zip_folder,
    find_word_files_in_folder,
)
from app.services.vectorstore import add_documents, stats, get_stored_sources
from app.services.rag import build_rag_chain
from app.schemas.rag import (
    AskRequest,
    AskResponse,
    FolderPathRequest,
    StoredSourcesResponse,
    SourceInfo,
)


router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/stats")
async def get_stats():
    import asyncio

    return await asyncio.to_thread(stats)


@router.get("/sources", response_model=StoredSourcesResponse)
async def get_stored_sources_list():
    """
    دریافت لیست تمام فایل‌های ذخیره شده در vectordb.

    این endpoint لیست تمام فایل‌هایی که در vectordb ذخیره شده‌اند را همراه با
    تعداد chunks هر فایل برمی‌گرداند.
    """
    import asyncio

    source_counts = await asyncio.to_thread(get_stored_sources)

    # تبدیل dictionary به لیست SourceInfo
    sources_list = [
        SourceInfo(source=source, chunk_count=count)
        for source, count in sorted(source_counts.items())
    ]

    total_chunks = sum(source_counts.values())

    return StoredSourcesResponse(
        total_files=len(source_counts),
        total_chunks=total_chunks,
        sources=sources_list,
    )


@router.get("/debug-sources")
def debug_sources():
    """
    Endpoint دیباگ برای بررسی دقیق وضعیت vectordb و فایل‌های ذخیره شده.
    """
    from app.services.vectorstore import get_vectorstore
    import logging

    logger = logging.getLogger(__name__)

    try:
        vs = get_vectorstore()
        collection = vs._collection

        # بررسی تعداد documents
        try:
            count = collection.count()
        except Exception as e:
            count = None
            error_count = str(e)

        # دریافت نمونه metadata
        try:
            sample = collection.get(limit=10)
            sample_metadatas = sample.get("metadatas", []) if sample else []
        except Exception as e:
            sample_metadatas = None
            error_sample = str(e)

        # دریافت همه metadata
        source_counts = get_stored_sources()

        debug_info = {
            "collection_count": count if count is not None else f"Error: {error_count}",
            "sample_metadatas_count": (
                len(sample_metadatas) if sample_metadatas else "Error getting sample"
            ),
            "sample_metadatas": [
                {
                    "keys": list(m.keys()) if isinstance(m, dict) else str(type(m)),
                    "source": m.get("source") if isinstance(m, dict) else None,
                }
                for m in (sample_metadatas[:5] if sample_metadatas else [])
            ],
            "unique_sources_found": len(source_counts),
            "sources": source_counts,
            "stats": stats(),
        }

        if sample_metadatas is None:
            debug_info["error_sample"] = error_sample

        return debug_info

    except Exception as e:
        logger.error(f"Error in debug_sources: {e}", exc_info=True)
        return {
            "error": str(e),
            "stats": stats(),
        }


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


@router.post("/upload-folder-zip")
async def upload_folder_zip(zip_file: UploadFile = File(...)):
    """
    آپلود فایل ZIP حاوی فایل‌های Word و اضافه کردن همه آن‌ها به vectordb.

    فایل ZIP باید شامل فایل‌های Word (.docx, .doc) باشد.
    تمام فایل‌های Word از ZIP استخراج شده و به vectordb اضافه می‌شوند.
    """
    import zipfile
    import tempfile

    if not zip_file.filename:
        raise HTTPException(status_code=400, detail="نام فایل مشخص نشده است")

    if not zip_file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="فایل باید از نوع ZIP باشد")

    # ایجاد یک فولدر موقت برای استخراج
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # ذخیره فایل ZIP
        zip_path = temp_path / zip_file.filename
        content = await zip_file.read()
        zip_path.write_bytes(content)

        # استخراج و پردازش فایل‌های Word
        extract_to = temp_path / "extracted"
        try:
            documents = ingest_zip_folder(zip_path, extract_to)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="فایل ZIP معتبر نیست")
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"خطا در پردازش فایل ZIP: {str(e)}"
            )

        if not documents:
            raise HTTPException(
                status_code=400, detail="هیچ فایل Word معتبری در فایل ZIP پیدا نشد"
            )

        # اضافه کردن به vectordb
        added = add_documents(documents)

        unique_files = len(set(doc.metadata.get("source", "") for doc in documents))

        return {
            "status": "success",
            "message": "فایل‌های Word با موفقیت پردازش و به vectordb اضافه شدند",
            "files_processed": unique_files,
            "chunks_added": added,
        }


@router.post("/upload-folder-from-path")
async def upload_folder_from_path(
    folder_path: str = Body(..., embed=True),
    recursive: bool = Body(True, embed=True),
):
    """
    پردازش فولدر از مسیر محلی سرور و اضافه کردن همه فایل‌های Word آن به vectordb.

    این endpoint برای زمانی است که فایل‌ها از قبل در سرور موجود هستند.
    مسیر می‌تواند نسبی به BASE_DIR یا مطلق باشد.
    """
    # تبدیل مسیر به Path
    folder = Path(folder_path)

    # اگر مسیر نسبی است، آن را نسبت به BASE_DIR می‌سازیم
    if not folder.is_absolute():
        folder = BASE_DIR / folder

    # بررسی وجود فولدر
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"فولدر پیدا نشد: {folder}")

    if not folder.is_dir():
        raise HTTPException(
            status_code=400, detail=f"مسیر داده شده یک فولدر نیست: {folder}"
        )

    # پردازش فایل‌های Word
    try:
        documents = ingest_folder(folder, recursive=recursive)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در پردازش فولدر: {str(e)}")

    if not documents:
        raise HTTPException(
            status_code=400, detail="هیچ فایل Word معتبری در فولدر پیدا نشد"
        )

    # اضافه کردن به vectordb
    added = add_documents(documents)

    unique_files = len(set(doc.metadata.get("source", "") for doc in documents))

    return {
        "status": "success",
        "message": "فایل‌های Word با موفقیت پردازش و به vectordb اضافه شدند",
        "folder_path": str(folder),
        "files_processed": unique_files,
        "chunks_added": added,
    }


@router.post("/ask", response_model=AskResponse)
@limiter.limit(get_rate_limit_string())
async def ask(
    request: Request,
    req: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ارسال سوال به سیستم RAG. اگر conversation_id ارسال شود، سوال و پاسخ به صورت خودکار ذخیره می‌شوند.
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.info(
        "RAG /ask received",
        extra={
            "conversation_id": req.conversation_id,
            "top_k": req.top_k,
            "use_enhanced": req.use_enhanced_retrieval,
            # برای حفظ حریم، فقط بخشی از سوال لاگ می‌شود
            "question_preview": (req.question or "")[:200],
        },
    )

    k = req.top_k or DEFAULT_TOP_K
    conversation_id = req.conversation_id
    conversation = None

    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.user_id == current_user.id,
            )
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # ذخیره خودکار سوال کاربر در دیتابیس
        user_msg = Message(
            conversation_id=conversation.id,
            user_id=current_user.id,
            role="user",
            content=req.question,
        )
        db.add(user_msg)
        db.commit()
        db.refresh(user_msg)

        # خواندن تاریخچه از دیتابیس (بدون سوال جدید که تازه اضافه کردیم)
        previous_messages = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation.id,
                Message.id != user_msg.id,
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        memory = create_memory_from_messages(previous_messages)
    else:
        memory = None

    use_enhanced = (
        req.use_enhanced_retrieval if req.use_enhanced_retrieval is not None else True
    )

    try:
        rag = build_rag_chain(
            k=k, use_enhanced_retrieval=use_enhanced, memory=memory, use_reranking=True
        )
        # Run RAG in thread pool to avoid blocking
        import asyncio

        result = await asyncio.to_thread(rag, req.question)

        # بررسی اینکه result یک dict است و فیلدهای مورد نیاز را دارد
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from RAG chain, got {type(result)}")

        if "answer" not in result:
            raise ValueError("RAG result missing 'answer' field")

        # اطمینان از وجود فیلدهای مورد نیاز
        result.setdefault("answer", "")
        result.setdefault("sources", [])

        # ذخیره خودکار پاسخ دستیار اگر conversation_id وجود داشته باشد
        if conversation_id and conversation:
            try:
                answer = result.get("answer") or ""
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    user_id=current_user.id,
                    role="assistant",
                    content=answer or "پاسخی دریافت نشد",
                )
                db.add(assistant_msg)
                db.commit()
            except Exception as db_error:
                logger.warning(
                    f"Failed to save assistant message: {db_error}", exc_info=True
                )
                # ادامه می‌دهیم حتی اگر ذخیره نشد

        # ساخت و برگرداندن پاسخ

        try:
            # لاگ محتوای result برای دیباگ
            logger.debug(
                f"RAG result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}"
            )
            logger.debug(
                f"RAG result answer length: {len(result.get('answer', '')) if isinstance(result, dict) else 'N/A'}"
            )

            response = AskResponse(**result)
            return response
        except Exception as validation_error:
            logger.error(f"Failed to create AskResponse: {validation_error}")
            logger.error(
                f"Result type: {type(result)}, Result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}"
            )
            # در صورت خطا، سعی می‌کنیم پاسخ حداقلی بسازیم
            minimal_result = {
                "answer": (
                    result.get("answer", "خطا در ساخت پاسخ")
                    if isinstance(result, dict)
                    else "خطا در پردازش"
                ),
                "sources": (
                    result.get("sources", []) if isinstance(result, dict) else []
                ),
            }
            # اضافه کردن فیلدهای optional اگر موجود باشند
            if isinstance(result, dict):
                for key in [
                    "response_time_seconds",
                    "citation_count",
                    "citation_accuracy",
                    "domain",
                    "domain_label",
                    "domain_confidence",
                ]:
                    if key in result:
                        minimal_result[key] = result[key]

            return AskResponse(**minimal_result)

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error in RAG endpoint: {e}", exc_info=True)

        # بررسی اینکه آیا مشکل از Hugging Face timeout است
        error_msg = str(e).lower()
        if (
            "timeout" in error_msg
            or "huggingface" in error_msg
            or "connection" in error_msg
        ):
            raise HTTPException(
                status_code=503,
                detail="نمی‌توان به مدل‌های Hugging Face دسترسی پیدا کرد. لطفاً اتصال اینترنت خود را بررسی کنید یا از VPN استفاده کنید. اگر مشکل ادامه داشت، متغیر محیطی HF_TIMEOUT را افزایش دهید.",
            )
        raise HTTPException(status_code=500, detail=f"خطا در پردازش سوال: {str(e)}")


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
