# ناشناس‌سازی اطلاعات شخصی (PII) در سامانه «وکیل تو»

## چرا لازم است؟

پرس‌وجوهای حقوقی کاربران ممکن است شامل **کد ملی، شماره تماس، نام، آدرس و شماره پرونده** باشد.
این داده‌ها نباید به‌صورت خام به سرویس‌های خارجی LLM (مثل OpenAI) ارسال شوند.
ماژول PII قبل از فراخوانی مدل، مقادیر را با placeholder جایگزین می‌کند و بعد از پاسخ، برای نمایش به کاربر بازمی‌گرداند.

## چه کار می‌کند؟

فایل اصلی: `app/core/pii_anonymizer.py`

1. **`anonymize(text)`** → `(متن_ناشناس، list[PIIMapping])`
2. **`restore(text, mappings)`** → متن با مقادیر اصلی
3. **`anonymize_for_logging(text)`** → فقط برای لاگ (mapping دور ریخته می‌شود)
4. **`call_llm_with_pii_protection(invoke_fn, prompt)`** → پوشش anonymize → LLM → restore

Placeholderها یکتا هستند، مثلاً:

- `[PII_NATIONAL_ID_1]`
- `[PII_PHONE_1]`
- `[PII_NAME_1]`
- `[PII_ADDRESS_1]`
- `[PII_CASE_NUMBER_1]`

## یکپارچه‌سازی

در `app/services/rag.py` داخل `build_rag_chain` → `run()` / `run_fallback()`:

- سوال کاربر anonymize می‌شود قبل از retrieve / cache / LLM
- تاریخچه memory هم برای ارسال به مدل anonymize می‌شود
- کلید Redis روی متن anonymize‌شده است؛ پاسخ cache‌شده با placeholder نگه داشته می‌شود
- پاسخ نهایی برای کاربر restore می‌شود

در routeهای `/rag/ask` و `/conversations/{id}/ask` فقط **preview anonymize‌شده** لاگ می‌شود.

پیام‌های ذخیره‌شده در PostgreSQL برای خود کاربر به‌صورت اصلی باقی می‌مانند (برای UX گفتگو)؛ مسیر خطرناک ارسال به LLM پوشش داده شده است.

## تنظیمات محیطی

```env
PII_ANONYMIZATION_ENABLED=true
PII_NER_ENABLED=false
```

- `PII_ANONYMIZATION_ENABLED`: روشن/خاموش کردن کل ماژول
- `PII_NER_ENABLED`: هوک اختیاری برای NER فارسی (مثلاً hazm). پیش‌فرض خاموش است چون دقت NER فارسی کامل نیست و وابستگی سنگین است.

## الزامات امنیتی

- **Mapping فقط در حافظه** و فقط طول عمر یک درخواست؛ در لاگ/فایل/DB/Redis ذخیره نمی‌شود.
- لاگ‌ها باید از `anonymize_for_logging` استفاده کنند.
- تست‌ها تضمین می‌کنند بعد از anonymize، الگوی کد ملی معتبر / موبایل خام در خروجی نماند.

## محدودیت‌های شناخته‌شده

- تشخیص **نام** بدون عنوان (آقای/خانم) ضعیف است مگر NER فعال و مدل مناسب پیکربندی شود.
- آدرس‌ها بر اساس کلمات کلیدی هستند و ممکن است بخشی از جمله حقوقی بی‌گناه را بگیرند یا آدرس غیررسمی را از دست بدهند.
- اگر مدل LLM placeholder را تغییر دهد/حذف کند، restore ناقص می‌شود (در system prompt از مدل خواسته شده عیناً نگه دارد).
- کد ملی فقط با الگوریتم چک‌دیجیت معتبر جایگزین می‌شود؛ اعداد ۱۰رقمی نامعتبر دست‌نخورده می‌مانند.

## افزودن الگوی PII جدید

1. مقدار جدید به `PIIType` اضافه کنید.
2. پیشوند را در `_PLACEHOLDER_PREFIX` تعریف کنید.
3. یک regex (یا detector) در `_collect_spans` اضافه کنید.
4. تست round-trip و assertion «نماندن الگوی خام» بنویسید.
5. این سند را به‌روز کنید.

## تست

```bash
pytest tests/test_pii_anonymizer.py -q
```
