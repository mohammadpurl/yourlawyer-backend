import zipfile
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from app.services.ingestion import load_text_from_file, chunk_text


def find_word_files_in_folder(folder_path: Path) -> List[Path]:
    """
    پیدا کردن تمام فایل‌های Word در یک فولدر و زیرفولدرهایش.

    Args:
        folder_path: مسیر فولدر

    Returns:
        لیست مسیرهای فایل‌های Word (.docx, .doc)
    """
    word_files: List[Path] = []
    word_extensions = {".docx", ".doc"}

    if not folder_path.exists():
        raise ValueError(f"فولدر پیدا نشد: {folder_path}")

    if not folder_path.is_dir():
        raise ValueError(f"مسیر داده شده یک فولدر نیست: {folder_path}")

    # جستجوی بازگشتی در فولدر و زیرفولدرها
    for file_path in folder_path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in word_extensions:
            word_files.append(file_path)

    return word_files


def extract_word_files_from_zip(zip_path: Path, extract_to: Path) -> List[Path]:
    """
    استخراج فایل‌های Word از یک فایل zip.

    Args:
        zip_path: مسیر فایل zip
        extract_to: مسیر فولدر برای استخراج

    Returns:
        لیست مسیرهای فایل‌های Word استخراج شده
    """
    word_files: List[Path] = []
    word_extensions = {".docx", ".doc"}

    extract_to.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        # استخراج همه فایل‌ها
        zip_ref.extractall(extract_to)

        # پیدا کردن فایل‌های Word استخراج شده
        for file_path in extract_to.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in word_extensions:
                word_files.append(file_path)

    return word_files


def ingest_folder(folder_path: Path, recursive: bool = True) -> List[Document]:
    """
    پردازش تمام فایل‌های Word در یک فولدر و تبدیل به Documents.

    Args:
        folder_path: مسیر فولدر
        recursive: آیا در زیرفولدرها هم جستجو شود

    Returns:
        لیست Documents
    """
    if recursive:
        word_files = find_word_files_in_folder(folder_path)
    else:
        # فقط فایل‌های مستقیم در فولدر
        word_files = [
            f
            for f in folder_path.iterdir()
            if f.is_file() and f.suffix.lower() in {".docx", ".doc"}
        ]

    if not word_files:
        return []

    documents: List[Document] = []
    for file_path in word_files:
        try:
            content = load_text_from_file(file_path)
            # استفاده از نام فایل به عنوان source
            source_name = file_path.relative_to(folder_path).as_posix()
            documents.extend(chunk_text(content, source=source_name))
        except Exception as e:
            # اگر یک فایل خطا داد، ادامه می‌دهیم و بقیه را پردازش می‌کنیم
            print(f"خطا در پردازش فایل {file_path}: {e}")
            continue

    return documents


def ingest_zip_folder(zip_path: Path, extract_to: Path | None = None) -> List[Document]:
    """
    پردازش فایل zip و استخراج و پردازش فایل‌های Word داخل آن.

    Args:
        zip_path: مسیر فایل zip
        extract_to: مسیر برای استخراج (اگر None باشد، در UPLOAD_DIR استخراج می‌شود)

    Returns:
        لیست Documents
    """
    from app.core.config import UPLOAD_DIRECTORY

    if extract_to is None:
        # استخراج در یک فولدر موقت در UPLOAD_DIR
        extract_to = UPLOAD_DIRECTORY / "temp_extracted" / zip_path.stem

    word_files = extract_word_files_from_zip(zip_path, extract_to)

    if not word_files:
        return []

    documents: List[Document] = []
    for file_path in word_files:
        try:
            content = load_text_from_file(file_path)
            # استفاده از نام فایل به عنوان source
            source_name = file_path.relative_to(extract_to).as_posix()
            documents.extend(chunk_text(content, source=source_name))
        except Exception as e:
            print(f"خطا در پردازش فایل {file_path}: {e}")
            continue

    return documents
