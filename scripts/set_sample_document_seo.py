"""Apply manual seo_title/seo_description overrides to specific sample_documents rows.

Source of truth for WHY these 11 documents were picked: real Google Search
Console query data (yourlawyeer.ir-Performance-on-Search-2026-09-05.xlsx) —
each is either a "quick win" (decent ranking, low CTR because title doesn't
match the exact phrase users search) or an existing document that matches a
real query well in content but ranks very poorly (position 60-95), suggesting
a title/on-page relevance problem rather than missing content.

Safety: dry-run by default — only prints the diff (current vs proposed).
Nothing is written to the database unless you pass --apply. Review the
printed diff first; these titles/descriptions directly affect live search
rankings for pages that already earn clicks.

Usage:
    python scripts/set_sample_document_seo.py            # dry run (default)
    python scripts/set_sample_document_seo.py --apply     # actually writes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.models.sample_document import SampleDocument  # noqa: E402

# id -> (seo_title, seo_description, source_query, gsc_impressions, gsc_position)
#
# seo_title values here match the frontend map exactly
# (your-lawyer-front-next/app/lib/sample-document-seo.ts SEO_OVERRIDES).
# They deliberately OMIT the "| وکیل تو" suffix — the Next.js root layout
# applies `title.template = "%s | وکیل تو"`, so adding it here would double it.
OVERRIDES: dict[int, tuple[str, str, str, int, float]] = {
    626: (
        "نمونه اظهارنامه مطالبه وجه و خسارت تاخیر تادیه چک",
        "نمونه اظهارنامه مطالبه وجه و خسارت تاخیر تادیه چک متعلق به شرکت — "
        "متن آماده و قابل دانلود رایگان به‌صورت PDF.",
        "نمونه اظهارنامه مطالبه وجه و خسارت تاخیر تادیه",
        176,
        6.39,
    ),
    263: (
        "دادخواست الزام به تمکین (زوجه) | نمونه PDF رایگان",
        "نمونه دادخواست الزام به تمکین همسر (زوجه) به‌صورت متن کامل و فایل "
        "PDF رایگان — قابل دانلود در کتابخانه وکیل تو.",
        "دادخواست الزام به تمکین pdf",
        149,
        8.79,
    ),
    364: (
        "نمونه سند خودرو مزایده‌ای (وکالت‌نامه خرید و تعویض پلاک)",
        "نمونه سند/وکالت‌نامه خرید خودروی مزایده‌ای و تعویض پلاک — متن آماده، "
        "رایگان و قابل دانلود PDF.",
        "نمونه سند خودرو مزایده ای",
        179,
        8.23,
    ),
    423: (
        "متن وکالت‌نامه تام‌الاختیار خرید و فروش | نمونه PDF",
        "متن کامل نمونه وکالت‌نامه تام‌الاختیار (کلی) خرید و فروش، آماده برای "
        "دانلود رایگان به‌صورت PDF.",
        "متن وکالت نامه تام الاختیار pdf",
        110,
        6.90,
    ),
    672: (
        "اساسنامه شرکت تعاونی مسکن | نمونه PDF رایگان",
        "نمونه اساسنامه شرکت تعاونی مسکن، متن کامل و قابل دانلود رایگان "
        "به‌صورت PDF برای ثبت شرکت.",
        "اساسنامه تعاونی مسکن pdf",
        101,
        5.63,
    ),
    651: (
        "نمونه اساسنامه شرکت سهامی خاص (PDF رایگان)",
        "نمونه اساسنامه شرکت سهامی خاص، متن کامل و آماده دانلود رایگان "
        "به‌صورت فایل PDF.",
        "نمونه اساسنامه شرکت سهامی خاص pdf",
        96,
        8.26,
    ),
    663: (
        "اساسنامه شرکت تعاونی (نمونه PDF رایگان)",
        "نمونه اساسنامه شرکت تعاونی، متن کامل و قابل دانلود رایگان به‌صورت "
        "PDF برای ثبت شرکت تعاونی.",
        "اساسنامه شرکت تعاونی pdf",
        93,
        8.20,
    ),
    611: (
        "اظهارنامه تخلیه ملک به علت اتمام قرارداد اجاره | نمونه PDF",
        "نمونه اظهارنامه تخلیه ملک مسکونی به علت اتمام (انقضای) مدت قرارداد "
        "اجاره، متن کامل و قابل دانلود رایگان.",
        "نمونه اظهارنامه تخلیه ملک به علت اتمام قرارداد",
        76,
        9.66,
    ),
    # --- existing content that matches a real query well but ranks very
    # poorly (position 60-95) -- likely an on-page relevance / title problem,
    # not missing content. Found by cross-referencing GSC low-position pages
    # against the sample_documents catalog.
    21: (
        "نمونه قولنامه ماشین (خرید و فروش خودرو)",
        "نمونه قولنامه ماشین / خودرو، متن کامل قرارداد خرید و فروش، رایگان "
        "و قابل دانلود PDF.",
        "نمونه قولنامه ماشین",
        36,
        95.75,
    ),
    654: (
        "مدارک لازم برای ثبت شرکت با مسئولیت محدود",
        "فهرست کامل مدارک مورد نیاز برای ثبت شرکت با مسئولیت محدود، رایگان "
        "و قابل دانلود.",
        "مدارک لازم برای ثبت شرکت با مسئولیت محدود",
        25,
        74.16,
    ),
    32: (
        "دانلود فرم قرارداد کار (نمونه رسمی وزارت کار)",
        "نمونه رسمی فرم قرارداد کار مطابق قالب وزارت تعاون، کار و رفاه "
        "اجتماعی، رایگان و قابل دانلود PDF.",
        "دانلود فرم قرارداد کار",
        32,
        89.22,
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to the DB")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(SampleDocument)
            .filter(SampleDocument.id.in_(OVERRIDES.keys()))
            .all()
        )
        by_id = {r.id: r for r in rows}
        missing = set(OVERRIDES) - set(by_id)
        if missing:
            print(f"WARNING: ids not found in DB, skipping: {sorted(missing)}")

        print(f"{'APPLYING' if args.apply else 'DRY RUN (no writes)'} — "
              f"{len(by_id)} document(s)\n")

        for doc_id, (seo_title, seo_desc, query, impr, pos) in OVERRIDES.items():
            row = by_id.get(doc_id)
            if not row:
                continue
            print(f"--- id={doc_id}  title={row.title!r}")
            print(f"    target query: {query!r}  (impressions={impr}, position={pos})")
            print(f"    seo_title:       {row.seo_title!r} -> {seo_title!r}")
            print(f"    seo_description: {row.seo_description!r} -> {seo_desc!r}")
            if args.apply:
                row.seo_title = seo_title
                row.seo_description = seo_desc
            print()

        if args.apply:
            db.commit()
            print("Applied and committed.")
        else:
            print("Dry run only — re-run with --apply to write these changes.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
