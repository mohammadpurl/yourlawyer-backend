# عیب‌یابی: چرا فایل‌ها در ChromaDB ذخیره نشده‌اند؟

## بررسی سریع

### 1. بررسی تعداد documents در ChromaDB

ابتدا endpoint `/rag/stats` را چک کنید:

```bash
GET http://localhost:8000/rag/stats
```

**اگر `num_vectors: 0` بود:**
- فایل‌ها واقعاً آپلود نشده‌اند یا خطا داده‌اند
- به مرحله بعد بروید

**اگر `num_vectors > 0` بود:**
- فایل‌ها آپلود شده‌اند اما endpoint `/rag/sources` مشکل دارد
- به بخش "مشکل در خواندن" بروید

### 2. بررسی دقیق‌تر با endpoint دیباگ

از endpoint جدید استفاده کنید:

```bash
GET http://localhost:8000/rag/debug-sources
```

این endpoint اطلاعات دقیقی می‌دهد:
- تعداد documents در collection
- نمونه metadata ها
- خطاهای احتمالی

## علل احتمالی

### علت 1: فایل‌ها آپلود نشده‌اند

**بررسی:**
- آیا درخواست آپلود موفق بوده است؟
- آیا پیام "success" دریافت کرده‌اید؟
- آیا خطایی در لاگ‌های سرور وجود دارد؟

**راه حل:**
1. دوباره فایل‌ها را آپلود کنید
2. لاگ‌های سرور را بررسی کنید
3. مطمئن شوید که تعداد chunks > 0 بوده است

### علت 2: فایل‌ها پردازش نشده‌اند

**بررسی:**
- آیا فایل‌ها از نوع صحیح هستند؟ (فقط .docx, .doc, .pdf, .txt)
- آیا فایل‌ها خالی نیستند؟
- آیا خطایی در پردازش رخ داده است؟

**راه حل:**
- فایل‌های Word را با یک برنامه دیگر باز کنید و مطمئن شوید که معتبر هستند
- لاگ‌های پردازش را بررسی کنید

### علت 3: خطا در ذخیره‌سازی

**بررسی:**
- آیا خطای batch size رخ داده است؟ (باید با فیک جدید حل شده باشد)
- آیا خطای ChromaDB وجود دارد؟

**راه حل:**
- لاگ‌های سرور را بررسی کنید
- اگر خطای ChromaDB وجود دارد، collection را reset کنید:

```bash
DELETE http://localhost:8000/rag/reset?collection_name=legal-texts
```

سپس دوباره آپلود کنید.

### علت 4: مشکل در خواندن metadata

**بررسی:**
- آیا `num_vectors > 0` اما `total_files = 0` است؟
- از endpoint `/rag/debug-sources` استفاده کنید

**راه حل:**
- اگر metadata وجود ندارد، ممکن است فایل‌ها با فرمت قدیمی ذخیره شده باشند
- دوباره آپلود کنید

## چک‌لیست عیب‌یابی

### مرحله 1: بررسی آمار

```bash
curl http://localhost:8000/rag/stats
```

**نتیجه مورد انتظار:**
```json
{
  "persist_directory": "...",
  "collection": "legal-texts",
  "num_vectors": 1234  // باید > 0 باشد
}
```

### مرحله 2: بررسی دیباگ

```bash
curl http://localhost:8000/rag/debug-sources
```

**بررسی کنید:**
- `collection_count`: باید > 0 باشد
- `sample_metadatas`: باید metadata با فیلد `source` داشته باشد
- `unique_sources_found`: تعداد فایل‌های منحصر به فرد

### مرحله 3: بررسی لاگ‌ها

لاگ‌های سرور را برای خطاهای زیر بررسی کنید:
- `Error getting stored sources`
- `ChromaDB error`
- `Batch size exceeds maximum`
- `Error processing file`

### مرحله 4: تست آپلود دوباره

اگر همه چیز خالی است:

1. **Reset collection:**
   ```bash
   DELETE http://localhost:8000/rag/reset?collection_name=legal-texts
   ```

2. **آپلود دوباره یک فایل تست:**
   ```bash
   POST http://localhost:8000/rag/upload
   Content-Type: multipart/form-data
   files: [انتخاب یک فایل Word]
   ```

3. **بررسی فوری:**
   ```bash
   GET http://localhost:8000/rag/stats
   # باید num_vectors > 0 باشد
   ```

## مثال پاسخ endpoint دیباگ

### اگر همه چیز درست باشد:

```json
{
  "collection_count": 1234,
  "sample_metadatas_count": 10,
  "sample_metadatas": [
    {
      "keys": ["source", "chunk_index"],
      "source": "قانون مدني.pdf"
    }
  ],
  "unique_sources_found": 25,
  "sources": {
    "قانون مدني.pdf": 245,
    "قانون مجازات.pdf": 892
  },
  "stats": {
    "num_vectors": 1234
  }
}
```

### اگر مشکلی وجود داشته باشد:

```json
{
  "collection_count": 0,  // ❌ هیچ document ای وجود ندارد
  "sample_metadatas_count": 0,
  "unique_sources_found": 0,
  "stats": {
    "num_vectors": 0
  }
}
```

## اقدامات بعدی

1. **اگر `num_vectors = 0`:**
   - فایل‌ها را دوباره آپلود کنید
   - لاگ‌ها را بررسی کنید
   - مطمئن شوید که endpoint آپلود موفق بوده

2. **اگر `num_vectors > 0` اما `sources = []`:**
   - از endpoint `/rag/debug-sources` استفاده کنید
   - لاگ‌ها را برای خطا بررسی کنید
   - ممکن است نیاز به reset و آپلود مجدد باشد

3. **اگر همه چیز درست به نظر می‌رسد:**
   - مطمئن شوید که از collection name درست استفاده می‌کنید
   - مطمئن شوید که سرور restart شده است

## نیاز به کمک بیشتر؟

اگر مشکل حل نشد، اطلاعات زیر را ارسال کنید:

1. خروجی `GET /rag/stats`
2. خروجی `GET /rag/debug-sources`
3. آخرین لاگ‌های سرور
4. نوع فایل‌هایی که آپلود کرده‌اید

