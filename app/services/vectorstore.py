from typing import List
import os
import logging

from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

from app.core.config import PERSIST_DIRECTORY, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# افزایش timeout برای Hugging Face (به ثانیه)
HF_TIMEOUT = int(os.getenv("HF_TIMEOUT", "300"))  # پیش‌فرض 300 ثانیه (5 دقیقه)

# تنظیم timeout برای Hugging Face Hub قبل از import
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = str(HF_TIMEOUT)
os.environ["HF_HUB_DOWNLOAD_TIMEOUT_S"] = str(HF_TIMEOUT)


def get_embeddings() -> HuggingFaceEmbeddings:
    """Get embeddings model with increased timeout for slow connections."""
    try:
        # تنظیم timeout برای Hugging Face Hub (اگر قبلاً تنظیم نشده)
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(HF_TIMEOUT))

        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info(f"Embeddings model '{EMBEDDING_MODEL}' initialized successfully")
        return embeddings
    except Exception as e:
        logger.error(f"Failed to initialize embeddings model '{EMBEDDING_MODEL}': {e}")
        logger.error(
            "If you're experiencing timeout issues, try:\n"
            "1. Set HF_TIMEOUT environment variable to a higher value (e.g., 600 for 10 minutes)\n"
            "2. Check your internet connection\n"
            "3. Use a VPN if Hugging Face is blocked in your region\n"
            "4. Pre-download the model manually using: huggingface-cli download intfloat/multilingual-e5-base"
        )
        raise


def get_vectorstore(collection_name: str = "legal-texts") -> Chroma:
    embeddings = get_embeddings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIRECTORY,
    )


def add_documents(
    documents: List[Document], collection_name: str = "legal-texts"
) -> int:
    if not documents:
        return 0

    import logging

    logger = logging.getLogger(__name__)

    # ChromaDB حداکثر batch size حدود 5461 است، پس به batch های کوچکتر تقسیم می‌کنیم
    BATCH_SIZE = 5000  # کمی کمتر از حد مجاز برای اطمینان

    total_added = 0
    vs = get_vectorstore(collection_name)

    try:
        # تقسیم documents به batch های کوچکتر
        total_batches = (len(documents) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in range(0, len(documents), BATCH_SIZE):
            batch = documents[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            logger.info(
                f"Adding batch {batch_num}/{total_batches} ({len(batch)} documents)"
            )
            vs.add_documents(batch)
            total_added += len(batch)
            # Persist بعد از هر batch برای اطمینان از ذخیره داده‌ها
            vs.persist()

        logger.info(
            f"Successfully added {total_added} documents in {total_batches} batches"
        )
        return total_added

    except (TypeError, ValueError, AttributeError) as e:
        # Handle ChromaDB corruption: delete and recreate collection
        logger.warning(
            f"ChromaDB error during add_documents: {e}. "
            "Attempting to reset collection and retry with batches."
        )

        # Delete the corrupted collection
        try:
            import chromadb

            client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)
            try:
                client.delete_collection(collection_name)
                logger.info(f"Deleted corrupted collection: {collection_name}")
            except Exception as del_err:
                logger.warning(f"Could not delete collection: {del_err}")
        except Exception as client_err:
            logger.warning(f"Could not create ChromaDB client: {client_err}")

        # Recreate vectorstore and try again with batches
        vs = get_vectorstore(collection_name)
        total_added = 0
        total_batches = (len(documents) + BATCH_SIZE - 1) // BATCH_SIZE

        for i in range(0, len(documents), BATCH_SIZE):
            batch = documents[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            logger.info(
                f"Adding batch {batch_num}/{total_batches} ({len(batch)} documents) after reset"
            )
            vs.add_documents(batch)
            total_added += len(batch)
            # Persist بعد از هر batch
            vs.persist()

        logger.info(
            f"Successfully recreated collection and added {total_added} documents in {total_batches} batches"
        )
        return total_added


def get_stored_sources(collection_name: str = "legal-texts") -> dict[str, int]:
    """
    دریافت لیست تمام فایل‌های ذخیره شده در vectordb به همراه تعداد chunks هر فایل.

    Returns:
        Dictionary که key آن نام فایل (source) و value آن تعداد chunks است
    """
    import logging

    logger = logging.getLogger(__name__)
    vs = get_vectorstore(collection_name)

    try:
        collection = vs._collection

        # بررسی اینکه آیا collection خالی است
        try:
            count = collection.count()
            logger.info(f"Total documents in collection: {count}")
        except Exception as count_err:
            logger.warning(f"Could not count documents: {count_err}")
            return {}

        if count == 0:
            logger.info("Collection is empty")
            return {}

        # دریافت همه metadata ها از collection
        # استفاده از limit برای دریافت همه
        try:
            results = collection.get(limit=count if count else None)
        except Exception as get_err:
            logger.error(f"Error getting results: {get_err}")
            # اگر با limit خطا داد، بدون limit امتحان کنیم
            results = collection.get()

        if not results:
            logger.warning("No results from collection.get()")
            return {}

        metadatas = results.get("metadatas")
        if not metadatas:
            logger.warning("No metadatas in results")
            logger.debug(
                f"Results keys: {results.keys() if isinstance(results, dict) else 'Not a dict'}"
            )
            return {}

        logger.info(f"Found {len(metadatas)} metadata entries")

        # شمارش تعداد chunks برای هر source
        source_counts: dict[str, int] = {}
        for idx, metadata in enumerate(metadatas):
            if metadata and isinstance(metadata, dict):
                source_value = metadata.get("source")
                if source_value:
                    source = str(source_value)
                    source_counts[source] = source_counts.get(source, 0) + 1
                else:
                    logger.debug(
                        f"Metadata at index {idx} has no 'source' field: {metadata.keys()}"
                    )
            else:
                logger.debug(f"Metadata at index {idx} is not a dict: {type(metadata)}")

        logger.info(f"Found {len(source_counts)} unique sources")
        return source_counts

    except Exception as e:
        logger.error(f"Error getting stored sources: {e}", exc_info=True)
        return {}


def stats(collection_name: str = "legal-texts") -> dict:
    vs = get_vectorstore(collection_name)
    try:
        count = vs._collection.count()
    except Exception:
        count = 0
    return {
        "persist_directory": PERSIST_DIRECTORY,
        "collection": collection_name,
        "num_vectors": count,
    }
