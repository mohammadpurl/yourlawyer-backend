"""Convert «درخواست های زندانیان» sources into clean presentable PDFs
and build an index for the sample-documents catalog.

Usage (from repo root, Windows with Microsoft Word recommended):
  python scripts/prepare_prisoner_requests.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_ROOT = ROOT / "data"
SRC_DIR_NAME = "درخواست های زندانیان"
OUT_DIR_NAME = "outputs_prisoner_requests"
INDEX_NAME = "prisoner_requests_index.json"

# Explicit catalog: stable external_id, title, category, source filename match
# source: exact filename in SRC_DIR (or None for skip)
CATALOG: list[dict] = [
    {
        "id": "1",
        "title": "نمونه درخواست انتقال زندانی به زندان دیگر",
        "category": "انتقال زندانی",
        "source": "1126473474نمونه_درخواست_انتقال_زندانی_به_زندان_دیگر.pdf",
    },
    {
        "id": "2",
        "title": "نمونه لایحه تخفیف مجازات در جرایم مواد مخدر",
        "category": "تخفیف مجازات",
        "source": "2080969439نمونه_لایحه_تخفیف_مجازات_در_جرایم_مواد_مخدر.pdf",
    },
    {
        "id": "3",
        "title": "نمونه درخواست ملاقات وکیل با زندانی",
        "category": "ملاقات",
        "source": "272489580نمونه_درخواست_ملاقات_وکیل_با_زندانی.pdf",
    },
    {
        "id": "4",
        "title": "آیین‌نامه اجرایی شماره ۹۰۰۰ (سازمان زندان‌ها)",
        "category": "آیین‌نامه و مقررات",
        "source": "آیین نامه اجرایی شماره ۹۰۰۰.docx",
    },
    {
        "id": "5",
        "title": "ارائه خدمات مربوط به زندانیان ایرانی در خارج از کشور",
        "category": "خدمات و مددکاری",
        "source": "ارائه خدمات مربوط به زندانیان ایرانی در خارج از کشور.docx",
    },
    # id 6 (اعاده دادرسی.docx) removed: contained third-party lawyer advertisement
    {
        "id": "7",
        "title": "تخفیف و تبدیل حبس — شرایط قانونی و نمونه درخواست",
        "category": "تخفیف مجازات",
        "source": "تخفیف و تبدیل حبس شرایط قانونی و نمونه درخواست.docx",
    },
    {
        "id": "8",
        "title": "تخفیف مجازات جرایم مواد مخدر",
        "category": "تخفیف مجازات",
        "source": "تخفیف-مجازات-جرایم-مواد-مخدر.docx",
    },
    {
        "id": "9",
        "title": "درخواست عفو زندانی",
        "category": "عفو",
        "source": "تدرخواست عفو زندانی.docx",
    },
    {
        "id": "10",
        "title": "نمونه شکایت به دیوان عدالت اداری",
        "category": "دیوان عدالت اداری",
        "source": "دانلود رایگان نمونه شکایت به دیوان عدالت اداری PDF.docx",
    },
    {
        "id": "11",
        "title": "درخواست اشتغال در کارگاه زندان",
        "category": "اشتغال و کار در زندان",
        "source": "درخواست اشتغال در کارگاه زندان.docx",
    },
    {
        "id": "12",
        "title": "درخواست انتقال زندانی",
        "category": "انتقال زندانی",
        "source": "درخواست انتقال زندانی.docx",
    },
    {
        "id": "13",
        "title": "درخواست رأفت اسلامی در چارچوب قانون کیفری",
        "category": "عفو",
        "source": "درخواست رأفت اسلامی در چارچوب قانون کیفری.docx",
    },
    {
        "id": "14",
        "title": "درخواست عفو زندانی (نسخه PDF)",
        "category": "عفو",
        "source": "درخواست عفو زندانی.pdf",
    },
    {
        "id": "15",
        "title": "شرایط و مراحل درخواست مرخصی استعلاجی زندانیان",
        "category": "مرخصی",
        "source": "شرایط و مراحل درخواست مرخصی استعلاجی زندانیان.docx",
    },
    {
        "id": "16",
        "title": "قرار وثیقه",
        "category": "وثیقه و پابند",
        "source": "قرار وثیقه.docx",
    },
    {
        "id": "17",
        "title": "ملاقات با زندانی",
        "category": "ملاقات",
        "source": "ملاقات با زندانی.docx",
    },
    {
        "id": "18",
        "title": "نامه حقوق کودکان (پیمان)",
        "category": "خدمات و مددکاری",
        "source": "نامه حقوق کودکان پیمان.docx",
    },
    {
        "id": "19",
        "title": "نحوه ثبت درخواست عفو در سامانه ثنا",
        "category": "عفو",
        "source": "نحوه-ثبت-درخواست-عفو-در-سامانه-ثنا.docx",
    },
    {
        "id": "20",
        "title": "نمونه درخواست آزادی از حبس از طریق پابند الکترونیکی",
        "category": "وثیقه و پابند",
        "source": "نمونه درخواست آزادی از حبس از طریق پابند الکترونیکی.docx",
    },
    {
        "id": "21",
        "title": "نمونه درخواست اعمال ماده ۴۷۷ (تنظیمی وکیل دادگستری)",
        "category": "اعاده دادرسی و ماده ۴۷۷",
        "source": "نمونه درخواست اعمال ماده 477 تنظیمی توسط وکیل دادگستری.docx",
    },
    {
        "id": "22",
        "title": "نمونه شکایت به دیوان عدالت اداری (PDF)",
        "category": "دیوان عدالت اداری",
        "source": "نمونه شکایت به دیوان عدالت اداری.pdf",
    },
    {
        "id": "23",
        "title": "نمونه نامه درخواست عفو زندانی",
        "category": "عفو",
        "source": "نمونه نامه درخواست عفو زندانی.docx",
    },
    {
        "id": "24",
        "title": "چگونه از خدمات مددکاری برای کمک به زندانیان استفاده کنیم",
        "category": "خدمات و مددکاری",
        "source": "چگونه از خدمات مددکاری برای کمک به زندانیان استفاده کنیم.docx",
    },
]


def _safe_slug(title: str, max_len: int = 80) -> str:
    s = title.strip()
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", "_", s)
    s = s.replace("—", "-").replace("–", "-")
    return s[:max_len].rstrip("._")


def _word_docx_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    """Convert DOCX → PDF via Microsoft Word COM (Windows)."""
    import win32com.client  # type: ignore

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = None
    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        # Word needs absolute paths with backslashes
        src = str(docx_path.resolve())
        dst = str(pdf_path.resolve())
        doc = word.Documents.Open(src, ReadOnly=True)
        # 17 = wdFormatPDF
        doc.SaveAs(dst, FileFormat=17)
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()
        # Give Word a moment to release file locks
        time.sleep(0.4)


def prepare() -> dict:
    src_dir = DATA_ROOT / SRC_DIR_NAME
    out_dir = DATA_ROOT / OUT_DIR_NAME
    if not src_dir.is_dir():
        raise SystemExit(f"Source folder not found: {src_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    index_items: list[dict] = []
    ok = 0
    failed: list[str] = []
    skipped_html = "اشتغال به کار زندانیان _ دیده بان حقوق کار ایران.html"

    for item in CATALOG:
        eid = item["id"]
        title = item["title"]
        category = item["category"]
        source_name = item["source"]
        src = src_dir / source_name
        if not src.is_file():
            failed.append(f"missing:{source_name}")
            continue

        out_name = f"{eid}_{_safe_slug(title)}.pdf"
        dest = out_dir / out_name

        try:
            if src.suffix.lower() == ".pdf":
                shutil.copy2(src, dest)
            elif src.suffix.lower() in {".docx", ".doc"}:
                _word_docx_to_pdf(src, dest)
            else:
                failed.append(f"unsupported:{source_name}")
                continue

            if not dest.is_file() or dest.stat().st_size < 100:
                failed.append(f"empty:{source_name}")
                continue

            index_items.append(
                {
                    "item_id": eid,
                    "title": title,
                    "category": category,
                    "url": None,
                    "source_file": source_name,
                    "pdf": out_name,
                }
            )
            ok += 1
            print(f"OK  [{eid}] {title}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{source_name}: {exc}")
            print(f"FAIL [{eid}] {source_name}: {exc}")

    index_path = out_dir / INDEX_NAME
    index_path.write_text(
        json.dumps(index_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = {
        "ok": ok,
        "failed": failed,
        "skipped_note": f"Skipped HTML scrape: {skipped_html}",
        "out_dir": str(out_dir),
        "index": str(index_path),
        "count": len(index_items),
    }
    (ROOT / "storage" / "_prisoner_prepare_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    result = prepare()
    print(json.dumps({k: result[k] for k in ("ok", "count", "failed")}, ensure_ascii=False, indent=2))
