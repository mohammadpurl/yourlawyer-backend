# لیست فایل‌های ذخیره شده در VectorDB

## Endpoint جدید

برای مشاهده لیست تمام فایل‌هایی که در vectordb ذخیره شده‌اند، از endpoint زیر استفاده کنید:

```
GET /rag/sources
```

## استفاده

### از Swagger UI

1. به `http://localhost:8000/docs` بروید
2. endpoint `GET /rag/sources` را پیدا کنید
3. روی "Try it out" کلیک کنید
4. "Execute" را بزنید

### از Postman یا curl

```bash
curl http://localhost:8000/rag/sources
```

## پاسخ نمونه

```json
{
  "total_files": 25,
  "total_chunks": 17264,
  "sources": [
    {
      "source": "قانون امور گمركي.pdf",
      "chunk_count": 245
    },
    {
      "source": "قانون مجازات اسلامي.pdf",
      "chunk_count": 892
    },
    {
      "source": "قانون مدني.pdf",
      "chunk_count": 1234
    },
    ...
  ]
}
```

## فیلدهای پاسخ

- **total_files**: تعداد کل فایل‌های ذخیره شده
- **total_chunks**: تعداد کل chunks (قطعات متن) ذخیره شده
- **sources**: لیست فایل‌ها با جزئیات:
  - **source**: نام فایل
  - **chunk_count**: تعداد chunks این فایل

## مثال استفاده در Python

```python
import requests

response = requests.get("http://localhost:8000/rag/sources")
data = response.json()

print(f"تعداد فایل‌ها: {data['total_files']}")
print(f"تعداد chunks: {data['total_chunks']}")

for file_info in data['sources']:
    print(f"- {file_info['source']}: {file_info['chunk_count']} chunks")
```

## نکات

- ✅ لیست به ترتیب حروف الفبا مرتب می‌شود
- ✅ فقط فایل‌هایی که در vectordb ذخیره شده‌اند نمایش داده می‌شوند
- ✅ تعداد chunks نشان می‌دهد که هر فایل به چند قطعه تقسیم شده است
- ✅ اگر فایلی آپلود شده اما پردازش نشده، در لیست نمایش داده نمی‌شود

