from io import BytesIO
from pathlib import Path
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from docx import Document as DocxDocument

from app.core.security import decrypt_bytes
from .config import CHUNK_SIZE, CHUNK_OVERLAP


def _load_pdf_from_buffer(source: BytesIO | str) -> str:
    reader = PdfReader(source)
    texts = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def _load_docx_from_buffer(source: BytesIO | str) -> str:
    doc = DocxDocument(source)
    return "\n".join(p.text for p in doc.paragraphs)


def _load_txt_from_bytes(content: bytes) -> str:
    return content.decode("utf-8", errors="ignore")


def load_text_from_file(path: Path) -> Tuple[str, str]:
    """Load text from (optionally encrypted) file and return text plus source name."""

    suffix = path.suffix.lower()

    if suffix == ".enc":
        raw = decrypt_bytes(path.read_bytes())
        original_name = Path(path.stem).name
        original_suffix = Path(original_name).suffix.lower()
        buffer = BytesIO(raw)

        if original_suffix == ".pdf":
            return _load_pdf_from_buffer(buffer), original_name
        if original_suffix in {".docx", ".doc"}:
            return _load_docx_from_buffer(buffer), original_name
        if original_suffix in {".txt", ".md"}:
            return _load_txt_from_bytes(raw), original_name
        raise ValueError(f"Unsupported encrypted file type: {original_suffix}")

    if suffix == ".pdf":
        return _load_pdf_from_buffer(path.as_posix()), path.name
    if suffix in {".docx", ".doc"}:
        return _load_docx_from_buffer(path.as_posix()), path.name
    if suffix in {".txt", ".md"}:
        return _load_txt_from_bytes(path.read_bytes()), path.name

    raise ValueError(f"Unsupported file type: {suffix}")


def chunk_text(text: str, source: str) -> List[Document]:
    # Persian-aware separators
    separators = [
        "\n\n",
        "\n",
        "۔",  # urdu/persian full stop
        ".",
        "!",
        "؟",
        "?",
        ";",
        "،",
        ",",
        " "
    ]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=separators,
        add_start_index=True,
    )
    docs = splitter.create_documents([text], metadatas=[{"source": source}])
    return docs


def ingest_files(paths: List[Path]) -> List[Document]:
    documents: List[Document] = []
    for p in paths:
        content, source_name = load_text_from_file(p)
        docs = chunk_text(content, source=source_name)
        documents.extend(docs)
    return documents

