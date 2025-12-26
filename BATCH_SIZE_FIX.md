# رفع مشکل Batch Size در ChromaDB

## مشکل

هنگام آپلود تعداد زیادی فایل Word، خطای زیر رخ می‌داد:

```
ValueError: Batch size 17264 exceeds maximum batch size 5461
```

## علت

ChromaDB محدودیت دارد و نمی‌تواند بیش از ~5461 document را در یک batch اضافه کند.

## راه حل

تابع `add_documents` در `app/services/vectorstore.py` به‌روزرسانی شد تا:

1. ✅ **تقسیم به batch های کوچکتر**: Documents به batch های 5000 تایی تقسیم می‌شوند
2. ✅ **ذخیره بعد از هر batch**: بعد از هر batch، داده‌ها persist می‌شوند
3. ✅ **لاگ پیشرفت**: تعداد batch ها و پیشرفت نمایش داده می‌شود

### نحوه کار

```python
# قبل: همه documents در یک batch
vs.add_documents(all_documents)  # ❌ خطا اگر > 5461

# بعد: تقسیم به batch های کوچکتر
for batch in batches:  # هر batch حداکثر 5000 document
    vs.add_documents(batch)  # ✅ کار می‌کند
    vs.persist()  # ذخیره بعد از هر batch
```

## استفاده

همه endpoint های آپلود به صورت خودکار از batch processing استفاده می‌کنند:

- `POST /rag/upload` - آپلود فایل‌های تکی
- `POST /rag/upload-folder-zip` - آپلود ZIP
- `POST /rag/upload-folder-from-path` - پردازش فولدر از مسیر

## نکات

- ✅ می‌توانید هر تعداد فایل Word آپلود کنید
- ✅ پردازش به صورت خودکار به batch تقسیم می‌شود
- ✅ لاگ‌ها نشان می‌دهند که چند batch پردازش شده است
- ✅ اگر خطایی در یک batch پیش آید، batch های قبلی ذخیره شده‌اند

## مثال لاگ

```
INFO | Adding batch 1/4 (5000 documents)
INFO | Adding batch 2/4 (5000 documents)
INFO | Adding batch 3/4 (5000 documents)
INFO | Adding batch 4/4 (2264 documents)
INFO | Successfully added 17264 documents in 4 batches
```

