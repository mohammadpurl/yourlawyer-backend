from typing import List, Optional, Set
import os
import logging

from app.core.config import HF_TIMEOUT, PERSIST_DIRECTORY, EMBEDDING_MODEL, HF_HOME

# Must configure Hugging Face Hub before importing huggingface-dependent packages.


def _configure_huggingface_hub() -> None:
    """Apply Hugging Face Hub settings safe for environments without hf_transfer."""
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(HF_TIMEOUT))
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT_S", str(HF_TIMEOUT))

    wants_hf_transfer = os.getenv("HF_HUB_ENABLE_HF_TRANSFER", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if wants_hf_transfer:
        try:
            import hf_transfer  # noqa: F401
        except ImportError:
            os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
            logging.getLogger(__name__).warning(
                "HF_HUB_ENABLE_HF_TRANSFER is enabled but hf_transfer is not installed; "
                "using standard download. Install with: pip install hf_transfer"
            )
            return

    # Force standard downloader unless hf_transfer is explicitly available.
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"


_configure_huggingface_hub()

from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

from app.services.ingestion import hash_page_content

logger = logging.getLogger(__name__)

_embeddings_cache: HuggingFaceEmbeddings | None = None


def _get_chroma_collection(collection_name: str = "legal-texts"):
    """Access Chroma collection without loading the embedding model."""
    import chromadb

    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)
    try:
        return client.get_collection(collection_name)
    except Exception:
        return None


def get_embeddings() -> HuggingFaceEmbeddings:
    """Get embeddings model with increased timeout for slow connections."""
    global _embeddings_cache
    if _embeddings_cache is not None:
        return _embeddings_cache

    _configure_huggingface_hub()
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info(f"Embeddings model '{EMBEDDING_MODEL}' initialized successfully")
        _embeddings_cache = embeddings
        return embeddings
    except Exception as e:
        error_text = str(e).lower()
        logger.error(f"Failed to initialize embeddings model '{EMBEDDING_MODEL}': {e}")
        if "not enough space" in error_text or "no space" in error_text:
            logger.error(
                "Disk space is insufficient for downloading the embedding model (~1.1 GB). "
                f"Free space on the cache drive or set HF_HOME to a drive with enough space. "
                f"Current HF_HOME: {HF_HOME}"
            )
        logger.error(
            "If you're experiencing timeout or network issues, try:\n"
            "1. Run: python scripts/download_embedding_model.py\n"
            "2. Set HF_ENDPOINT=https://hf-mirror.com if huggingface.co is blocked\n"
            "3. Set HF_TIMEOUT=1200 for slow connections\n"
            "4. Place a local model in storage/models/multilingual-e5-base\n"
            f"5. Current HF_HOME: {HF_HOME}"
        )
        raise


def ensure_embeddings_ready() -> None:
    """Load embedding model early so bulk ingest fails fast with a clear error."""
    get_embeddings()


def get_vectorstore(collection_name: str = "legal-texts") -> Chroma:
    embeddings = get_embeddings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIRECTORY,
    )


def get_existing_content_hashes(collection_name: str = "legal-texts") -> Set[str]:
    """Return content hashes for all vectors (metadata or computed from page_content)."""
    try:
        collection = _get_chroma_collection(collection_name)
        if collection is None:
            return set()

        count = collection.count()
        if count == 0:
            return set()

        hashes: Set[str] = set()
        from_metadata = 0
        from_content = 0
        batch_size = 5000

        for offset in range(0, count, batch_size):
            batch = collection.get(
                limit=min(batch_size, count - offset),
                offset=offset,
                include=["metadatas", "documents"],
            )
            metadatas = batch.get("metadatas") or []
            documents = batch.get("documents") or []

            for idx, metadata in enumerate(metadatas):
                content_hash = None
                if metadata and isinstance(metadata, dict):
                    content_hash = metadata.get("content_hash")

                if content_hash:
                    hashes.add(str(content_hash))
                    from_metadata += 1
                elif idx < len(documents) and documents[idx]:
                    hashes.add(hash_page_content(documents[idx]))
                    from_content += 1

        logger.info(
            "Loaded %s unique content hashes from Chroma (%s from metadata, %s from page_content)",
            len(hashes),
            from_metadata,
            from_content,
        )
        return hashes
    except Exception as exc:
        logger.warning(f"Could not load existing content hashes: {exc}")
        return set()


def _prepare_documents_for_insert(
    documents: List[Document], existing_hashes: Set[str]
) -> tuple[List[Document], List[str], int]:
    """Filter duplicates and assign stable IDs based on content_hash."""
    prepared: List[Document] = []
    ids: List[str] = []
    skipped = 0

    for doc in documents:
        metadata = dict(doc.metadata or {})
        content_hash = metadata.get("content_hash")
        if not content_hash:
            content_hash = hash_page_content(doc.page_content)
            metadata["content_hash"] = content_hash

        if content_hash in existing_hashes:
            skipped += 1
            continue

        existing_hashes.add(content_hash)
        prepared.append(Document(page_content=doc.page_content, metadata=metadata))
        ids.append(str(content_hash))

    return prepared, ids, skipped


def add_documents(
    documents: List[Document],
    collection_name: str = "legal-texts",
    existing_hashes: Optional[Set[str]] = None,
) -> int:
    if not documents:
        return 0

    import logging

    logger = logging.getLogger(__name__)

    if existing_hashes is None:
        existing_hashes = get_existing_content_hashes(collection_name)
    documents, doc_ids, skipped = _prepare_documents_for_insert(
        documents, existing_hashes
    )
    if skipped:
        logger.info(f"Skipped {skipped} duplicate chunks already in collection")
    if not documents:
        logger.info("No new documents to add after deduplication")
        return 0

    # ChromaDB حداکثر batch size حدود 5461 است، پس به batch های کوچکتر تقسیم می‌کنیم
    BATCH_SIZE = 5000  # کمی کمتر از حد مجاز برای اطمینان

    total_added = 0
    vs = get_vectorstore(collection_name)

    try:
        # تقسیم documents به batch های کوچکتر
        total_batches = (len(documents) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in range(0, len(documents), BATCH_SIZE):
            batch = documents[i : i + BATCH_SIZE]
            batch_ids = doc_ids[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            logger.info(
                f"Adding batch {batch_num}/{total_batches} ({len(batch)} documents)"
            )
            vs.add_documents(batch, ids=batch_ids)
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
            batch_ids = doc_ids[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            logger.info(
                f"Adding batch {batch_num}/{total_batches} ({len(batch)} documents) after reset"
            )
            vs.add_documents(batch, ids=batch_ids)
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
    collection = _get_chroma_collection(collection_name)

    try:
        if collection is None:
            logger.info("Collection does not exist yet")
            return {}

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
    collection = _get_chroma_collection(collection_name)
    try:
        count = collection.count() if collection is not None else 0
    except Exception:
        count = 0
    return {
        "persist_directory": PERSIST_DIRECTORY,
        "collection": collection_name,
        "num_vectors": count,
    }
