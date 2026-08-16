# وضعیت Roadmap وکیل تو ↔ ریپو (به‌روز)

اصل ثابت: **هیچ تغییر pipeline بدون eval قبل/بعد.**

## پیشرفت لایه ۱–۲ (این اجرا)

| آیتم | وضعیت |
|--|--|
| Encoding audit | `scripts/audit_chroma_encoding.py` — sample ۸۰۰۰: bad_rate≈۴.۱٪؛ گزارش `storage/encoding_audit_report.json`؛ purge فقط با `--purge --purge-confirm YES_PURGE_BAD_ENCODING` |
| Domain tagging | mapping گسترش یافت؛ backfill کامل corpus ≈۶۶.۶٪ tagged / ≈۳۳.۴٪ unclassified؛ روی قوانین پرتکرار اولویت‌دار نزدیک صفر unclassified؛ فیلتر دامنه **خاموش** (`ENABLE_DOMAIN_FILTERED_RETRIEVAL=false`) |
| Work/tamin | ingest سرور قبلاً انجام شده |
| Criminal pilot | `scripts/ingest_criminal_pilot.py` + validate ۴ فایل در `data/outputs_criminal` (کیفیت OK)؛ محتوای اصلی در Chroma (dedupe)؛ گزارش‌ها در `storage/criminal_*` |
| Eval set | `eval/questions.jsonl` = **۱۲۰** سؤال واقعی (بدون PLACEHOLDER؛ رسمی/محاوره؛ labor/meta/…) |
| Baseline | `eval/results/baseline_roadmap.json` (۴۰ سؤال: ۲۹ answered، ۸ low-conf، ۲ refused) |
| KPI traces | `scripts/report_query_trace_kpis.py` → `storage/query_trace_kpi_report.json` |
| Guidance review | `storage/general_guidance_review_samples.md` — ۱۵ نمونه static؛ flag سطح-۳ هنوز **false** |

## لایه ۳ عمداً متوقف (defer)

تا وقتی گیت لایه ۱+۲ برقرار نشده:

- Hybrid dense + BM25 — **پیاده‌سازی نشود**
- Query rewriting مشروط — **پیاده‌سازی نشود**
- `ENABLE_DOMAIN_FILTERED_RETRIEVAL` — **خاموش بماند** تا unclassified کلی و eval پایدارتر شوند

گیت ورود به لایه ۳:

1. Encoding audit نزدیک صفر bad روی sample بزرگ (الان ~۴٪ — purge انتخابی بعد از review گزارش)
2. Unclassified قابل‌قبول‌تر (هدف کمتر از ۲۰٪ کلی؛ الان ~۳۳٪؛ اولویت‌دارها عمدتاً tagged)
3. Eval set ≥۵۰ سؤال واقعی + baseline در `eval/results/` — **انجام شد** (۱۲۰ + baseline ۴۰)
4. Work/tamin و pilot کیفری بدون refuse بی‌مورد روی سؤالات پوشش‌دار

## لایه ۴

- امتناع شفاف + سطح-۳ در کد هستند؛ flag سطح-۳ پیش‌فرض **false** تا تأیید کتبی review تمام شود.
- صفحه شفافیت پوشش: هنوز فرانت/محتوا — خارج از این ریپو.
