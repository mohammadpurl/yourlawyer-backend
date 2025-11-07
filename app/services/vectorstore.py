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
    vs = get_vectorstore(collection_name)
    vs.add_documents(documents)
    vs.persist()
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
