from pathlib import Path
from typing import List, Tuple
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pypdf import PdfReader

try:
    from docx import Document as DocxDocument  # type: ignore

    _HAS_DOCX = True
except Exception:
    DocxDocument = None  # type: ignore
    _HAS_DOCX = False

from app.core.config import CHUNK_SIZE, CHUNK_OVERLAP


def _load_pdf(path: Path) -> str:
    reader = PdfReader(path.as_posix())
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _load_docx(path: Path) -> str:
    if not _HAS_DOCX:
        raise ImportError(
            "python-docx is not installed. Install with 'pip install python-docx' to load DOCX files."
        )
    doc = DocxDocument(path.as_posix())  # type: ignore
    return "\n".join(p.text for p in doc.paragraphs)


def _load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def load_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix in {".docx", ".doc"}:
        return _load_docx(path)
    if suffix in {".txt", ".md"}:
        return _load_txt(path)
    raise ValueError(f"Unsupported file type: {suffix}")


def _find_legal_units(text: str) -> List[Tuple[int, int, str, str]]:
    """Return list of (start, end, kind, title) ranges for Persian legal units.

    Kinds: ماده, اصل, تبصره, بند. Supports Persian/Latin digits.
    """
    # Heading pattern with optional number/title
    digit = r"[0-9\u06F0-\u06F9]+"
    kinds = ["ماده", "اصل", "تبصره", "بند"]
    # Lookahead split points for headings at line starts or after double newline
    pattern = re.compile(rf"(?m)(?=^(?:{'|'.join(kinds)})\s+{digit}[^\n]*$)")

    # Collect indices of headings
    indices = [m.start() for m in pattern.finditer(text)]
    if not indices:
        return []
    ranges: List[Tuple[int, int, str, str]] = []
    indices.append(len(text))
    for i in range(len(indices) - 1):
        start = indices[i]
        end = indices[i + 1]
        header_line = text[
            start : text.find("\n", start, end) if "\n" in text[start:end] else end
        ]
        kind_match = re.match(
            rf"^(?P<kind>{'|'.join(kinds)})\s+(?P<num>{digit})(?P<rest>[^\n]*)",
            header_line,
        )
        if kind_match:
            kind = kind_match.group("kind")
            title = (kind_match.group("num") + (kind_match.group("rest") or "")).strip()
        else:
            kind = "بخش"
            title = header_line.strip()
        ranges.append((start, end, kind, title))
    return ranges


def _legal_chunk_documents(text: str, source: str) -> List[Document]:
    units = _find_legal_units(text)
    documents: List[Document] = []
    if units:
        for idx, (s, e, kind, title) in enumerate(units):
            content = text[s:e].strip()
            if not content:
                continue
            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": source,
                        "unit_kind": kind,
                        "unit_title": title,
                        "unit_index": idx,
                    },
                )
            )
        return documents

    # Fallback to general splitter if no legal units detected
    separators = ["\n\n", "\n", "۔", ".", "!", "؟", "?", ";", "،", ",", " "]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=separators,
        add_start_index=True,
    )
    return splitter.create_documents([text], metadatas=[{"source": source}])


def chunk_text(text: str, source: str) -> List[Document]:
    return _legal_chunk_documents(text, source)


def ingest_files(paths: List[Path]) -> List[Document]:
    documents: List[Document] = []
    for p in paths:
        content = load_text_from_file(p)
        documents.extend(chunk_text(content, source=p.name))
    return documents
