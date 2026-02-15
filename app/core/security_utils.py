"""
ابزارهای امنیتی برای محافظت در برابر آسیب‌پذیری‌های رایج
"""

import os
import re
import zipfile
from pathlib import Path
from typing import List, Tuple
from fastapi import HTTPException, UploadFile

# تلاش برای ایمپورت کتابخانه magic.
# در صورت عدم نصب، از بررسی بر اساس پسوند فایل استفاده می‌کنیم.
try:
    import magic  # python-magic-bin برای Windows، python-magic برای Linux
except ImportError:
    magic = None


# مسیرهای مجاز برای دسترسی
ALLOWED_BASE_DIRS = [
    Path(os.getenv("UPLOAD_DIR", "./data/uploads")).resolve(),
    Path(os.getenv("BASE_DIR", ".")).resolve() / "data",
]

# پسوندهای مجاز
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".zip"}

# حداکثر اندازه فایل (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

# حداکثر تعداد فایل در ZIP
MAX_FILES_IN_ZIP = 1000

# حداکثر عمق فولدر در ZIP
MAX_ZIP_DEPTH = 10


def sanitize_filename(filename: str) -> str:
    """
    پاکسازی نام فایل از کاراکترهای خطرناک

    Args:
        filename: نام فایل ورودی

    Returns:
        نام فایل پاکسازی شده
    """
    # حذف کاراکترهای خطرناک
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", filename)
    # حذف مسیرهای نسبی
    filename = filename.replace("..", "")
    # حذف فاصله‌های اضافی
    filename = filename.strip()
    # محدود کردن طول
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[: 255 - len(ext)] + ext
    return filename


def validate_file_extension(filename: str) -> bool:
    """
    بررسی پسوند فایل

    Args:
        filename: نام فایل

    Returns:
        True اگر پسوند مجاز باشد
    """
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def validate_file_content(file_path: Path) -> bool:
    """
    بررسی محتوای فایل با استفاده از magic numbers

    Args:
        file_path: مسیر فایل

    Returns:
        True اگر نوع فایل معتبر باشد
    """
    try:
        # استفاده از python-magic برای بررسی نوع واقعی فایل
        mime = magic.Magic(mime=True)
        file_type = mime.from_file(str(file_path))

        # بررسی MIME types مجاز
        allowed_mimes = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
            "text/plain",
            "text/markdown",
            "application/zip",
        }

        return file_type in allowed_mimes
    except Exception:
        # اگر magic library نصب نباشد، فقط بر اساس پسوند بررسی می‌کنیم
        return validate_file_extension(file_path.name)


def validate_path(path: Path, base_dirs: List[Path] = None) -> Tuple[bool, Path]:
    """
    بررسی مسیر برای جلوگیری از Path Traversal

    Args:
        path: مسیر مورد بررسی
        base_dirs: لیست مسیرهای مجاز (پیش‌فرض: ALLOWED_BASE_DIRS)

    Returns:
        (is_valid: bool, resolved_path: Path)
    """
    if base_dirs is None:
        base_dirs = ALLOWED_BASE_DIRS

    try:
        # تبدیل به مسیر مطلق
        resolved = path.resolve()

        # بررسی اینکه مسیر در یکی از دایرکتوری‌های مجاز باشد
        for base_dir in base_dirs:
            base_resolved = base_dir.resolve()
            try:
                # بررسی اینکه resolved در داخل base_resolved باشد
                resolved.relative_to(base_resolved)
                return True, resolved
            except ValueError:
                continue

        return False, resolved
    except Exception:
        return False, path


def safe_extract_zip(zip_path: Path, extract_to: Path) -> List[Path]:
    """
    استخراج امن فایل ZIP با محافظت در برابر Zip Slip

    Args:
        zip_path: مسیر فایل ZIP
        extract_to: مسیر مقصد برای استخراج

    Returns:
        لیست مسیرهای فایل‌های استخراج شده
    """
    extracted_files: List[Path] = []
    extract_to = extract_to.resolve()

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        # بررسی تعداد فایل‌ها
        file_list = zip_ref.namelist()
        if len(file_list) > MAX_FILES_IN_ZIP:
            raise HTTPException(
                status_code=400,
                detail=f"تعداد فایل‌های ZIP بیش از حد مجاز است (حداکثر {MAX_FILES_IN_ZIP})",
            )

        for member in file_list:
            # بررسی مسیر فایل برای جلوگیری از Zip Slip
            member_path = Path(member)

            # بررسی عمق فولدر
            depth = len(member_path.parts)
            if depth > MAX_ZIP_DEPTH:
                raise HTTPException(
                    status_code=400,
                    detail=f"عمق فولدر بیش از حد مجاز است (حداکثر {MAX_ZIP_DEPTH})",
                )

            # بررسی مسیرهای نسبی خطرناک
            if ".." in member or member.startswith("/"):
                raise HTTPException(
                    status_code=400, detail="مسیرهای نسبی خطرناک در ZIP مجاز نیست"
                )

            # ساخت مسیر کامل
            target_path = extract_to / member_path

            # بررسی اینکه مسیر در داخل extract_to باشد
            try:
                target_path.resolve().relative_to(extract_to.resolve())
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="مسیر فایل در ZIP خارج از محدوده مجاز است"
                )

            # استخراج فایل
            zip_ref.extract(member, extract_to)
            extracted_path = extract_to / member_path

            if extracted_path.is_file():
                extracted_files.append(extracted_path)

    return extracted_files


def validate_upload_file(file: UploadFile) -> None:
    """
    اعتبارسنجی فایل آپلود شده

    Args:
        file: فایل آپلود شده

    Raises:
        HTTPException: در صورت نامعتبر بودن فایل
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="نام فایل مشخص نشده است")

    # پاکسازی نام فایل
    sanitized_name = sanitize_filename(file.filename)
    if sanitized_name != file.filename:
        raise HTTPException(
            status_code=400, detail="نام فایل شامل کاراکترهای غیرمجاز است"
        )

    # بررسی پسوند
    if not validate_file_extension(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"نوع فایل مجاز نیست. انواع مجاز: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # بررسی اندازه فایل (باید در endpoint انجام شود چون نیاز به خواندن فایل دارد)


def check_file_size(content: bytes) -> None:
    """
    بررسی اندازه فایل

    Args:
        content: محتوای فایل به صورت bytes

    Raises:
        HTTPException: در صورت بزرگ بودن فایل
    """
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"اندازه فایل بیش از حد مجاز است (حداکثر {MAX_FILE_SIZE / 1024 / 1024}MB)",
        )


def secure_path_join(base: Path, *parts: str) -> Path:
    """
    اتصال امن مسیرها با محافظت در برابر Path Traversal

    Args:
        base: مسیر پایه
        *parts: بخش‌های مسیر

    Returns:
        مسیر امن

    Raises:
        HTTPException: در صورت نامعتبر بودن مسیر
    """
    result = base
    for part in parts:
        # پاکسازی هر بخش
        part = sanitize_filename(part)
        if ".." in part or part.startswith("/"):
            raise HTTPException(
                status_code=400, detail="مسیر شامل کاراکترهای خطرناک است"
            )
        result = result / part

    # بررسی نهایی
    is_valid, resolved = validate_path(result)
    if not is_valid:
        raise HTTPException(status_code=400, detail="مسیر خارج از محدوده مجاز است")

    return resolved
