# ذخیره خودکار پیام‌ها

## خلاصه

**هر سوال و پاسخ به صورت خودکار در دیتابیس ذخیره می‌شود** - نیازی به درخواست جداگانه از فرانت نیست.

## Endpoints با ذخیره خودکار

### 1. `POST /conversations/{conversation_id}/ask` ✅

این endpoint به صورت کامل خودکار عمل می‌کند:

1. **سوال کاربر ذخیره می‌شود** (بلافاصله)
2. تاریخچه گفتگو خوانده می‌شود
3. سوال + تاریخچه به مدل ارسال می‌شود
4. **پاسخ مدل ذخیره می‌شود** (بلافاصله بعد از دریافت)
5. پاسخ به فرانت برگردانده می‌شود

```json
POST /conversations/123/ask
{
  "question": "قانون مجازات اسلامی چیست؟"
}

// نتیجه:
// ✅ سوال در دیتابیس ذخیره شد (با conversation_id=123)
// ✅ پاسخ در دیتابیس ذخیره شد (با conversation_id=123)
// ✅ پاسخ به فرانت برگردانده شد
```

### 2. `POST /rag/ask` ✅ (اگر conversation_id ارسال شود)

این endpoint نیز اگر `conversation_id` در request باشد، به صورت خودکار ذخیره می‌کند:

```json
POST /rag/ask
{
  "question": "قانون مجازات اسلامی چیست؟",
  "conversation_id": 123  // اختیاری
}

// اگر conversation_id موجود باشد:
// ✅ سوال در دیتابیس ذخیره شد
// ✅ پاسخ در دیتابیس ذخیره شد
// ✅ پاسخ به فرانت برگردانده شد

// اگر conversation_id نباشد:
// ✅ فقط پاسخ به فرانت برگردانده شد (بدون ذخیره)
```

## فرآیند خودکار

### مرحله 1: دریافت سوال
```
فرانت → POST /conversations/{id}/ask → Backend
```

### مرحله 2: ذخیره سوال (خودکار)
```python
user_msg = Message(
    conversation_id=conv.id,  # ✅ با conversation_id
    user_id=current_user.id,
    role="user",
    content=payload.question,
)
db.add(user_msg)
db.commit()  # ✅ ذخیره شد
```

### مرحله 3: تولید پاسخ
```
Backend → RAG Chain → OpenAI/LLM → پاسخ
```

### مرحله 4: ذخیره پاسخ (خودکار)
```python
assistant_msg = Message(
    conversation_id=conv.id,  # ✅ با همان conversation_id
    user_id=current_user.id,
    role="assistant",
    content=answer,
)
db.add(assistant_msg)
db.commit()  # ✅ ذخیره شد
```

### مرحله 5: بازگشت پاسخ به فرانت
```
Backend → پاسخ به فرانت
```

## نکات مهم

✅ **همه چیز خودکار است** - نیازی به درخواست جداگانه نیست  
✅ **سوال و پاسخ با همان conversation_id ذخیره می‌شوند**  
✅ **ترتیب ذخیره‌سازی حفظ می‌شود** (با `created_at`)  
✅ **می‌توانید با `GET /conversations/{id}` همه پیام‌ها را ببینید**

## مثال کامل

```bash
# 1. ایجاد گفتگو
POST /conversations
→ { "id": 123 }

# 2. ارسال سوال (ذخیره خودکار)
POST /conversations/123/ask
{
  "question": "قانون مجازات چیست؟"
}
→ { 
     "conversation_id": 123,
     "answer": "...",
     ...
   }
# ✅ سوال ذخیره شد
# ✅ پاسخ ذخیره شد

# 3. مشاهده تمام پیام‌ها
GET /conversations/123
→ {
     "id": 123,
     "messages": [
       {
         "id": 1,
         "role": "user",
         "content": "قانون مجازات چیست؟",
         "created_at": "2024-12-04T10:00:00"
       },
       {
         "id": 2,
         "role": "assistant",
         "content": "...",
         "created_at": "2024-12-04T10:00:05"
       }
     ]
   }
```

## نتیجه

**هیچ درخواست جداگانه‌ای برای ذخیره پیام‌ها لازم نیست!**  
همه چیز به صورت خودکار انجام می‌شود. ✅

