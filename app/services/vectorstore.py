from typing import List

from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

from app.core.config import PERSIST_DIRECTORY, EMBEDDING_MODEL


def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL, encode_kwargs={"normalize_embeddings": True}
    )


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

    try:
        vs = get_vectorstore(collection_name)
        vs.add_documents(documents)
        vs.persist()
        return len(documents)
    except (TypeError, ValueError, AttributeError) as e:
        # Handle ChromaDB corruption: delete and recreate collection
        logger.warning(
            f"ChromaDB error during add_documents: {e}. "
            "Attempting to reset collection."
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

        # Recreate vectorstore and try again
        vs = get_vectorstore(collection_name)
        vs.add_documents(documents)
        vs.persist()
        logger.info(
            f"Successfully recreated collection and added {len(documents)} documents"
        )
        return len(documents)


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
