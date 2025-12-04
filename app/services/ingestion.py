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


def _detect_document_type(source: str, text: str) -> str:
    """Detect document type from filename and content."""
    source_lower = source.lower()
    text_lower = text[:500].lower()  # Check first 500 chars

    if "قانون" in source_lower or "law" in source_lower:
        return "law"
    if (
        "آیین‌نامه" in source_lower
        or "regulation" in source_lower
        or "آیین نامه" in source_lower
    ):
        return "regulation"
    if "رای" in source_lower or "ruling" in source_lower or "حکم" in source_lower:
        return "ruling"
    if "قانون" in text_lower:
        return "law"
    if "آیین‌نامه" in text_lower or "آیین نامه" in text_lower:
        return "regulation"
    return "document"


def _detect_legal_domain(text: str) -> str:
    """Detect legal domain from content."""
    text_lower = text[:1000].lower()  # Check first 1000 chars

    domain_keywords = {
        "criminal": ["جرم", "مجازات", "کیفری", "زندان", "حبس"],
        "civil": ["حقوق مدنی", "عقد", "قرارداد", "ارث", "وصیت"],
        "family": ["خانواده", "ازدواج", "طلاق", "نفقه", "حضانت"],
        "commercial": ["تجاری", "شرکت", "سهامی", "چک", "برات"],
    }

    scores = {}
    for domain, keywords in domain_keywords.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[domain] = score

    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]
    return "unknown"


def _legal_chunk_documents(text: str, source: str) -> List[Document]:
    """Chunk legal documents with enhanced metadata."""
    document_type = _detect_document_type(source, text)
    legal_domain = _detect_legal_domain(text)

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
                        "document_type": document_type,
                        "legal_domain": legal_domain,
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
    docs = splitter.create_documents(
        [text],
        metadatas=[
            {
                "source": source,
                "document_type": document_type,
                "legal_domain": legal_domain,
            }
        ],
    )
    return docs


def chunk_text(text: str, source: str) -> List[Document]:
    return _legal_chunk_documents(text, source)


def ingest_files(paths: List[Path]) -> List[Document]:
    documents: List[Document] = []
    for p in paths:
        content = load_text_from_file(p)
        documents.extend(chunk_text(content, source=p.name))
    return documents
