# مستندات ذخیره‌سازی گفتگوها

## ذخیره‌سازی پیام‌ها

هر سوالی که توسط کاربر پرسیده می‌شود و پاسخ آن، به صورت خودکار در دیتابیس ذخیره می‌شود.

### ساختار ذخیره‌سازی

#### 1. سوال کاربر (User Message)
هنگامی که کاربر یک سوال می‌پرسد:
- **ذخیره می‌شود در جدول `messages`**
- **با `conversation_id`** مربوط به گفتگو
- **با `role="user"`**
- **با `content`** برابر با سوال کاربر
- **با `user_id`** مربوط به کاربر لاگین شده

```python
user_msg = Message(
    conversation_id=conv.id,  # ID گفتگو
    user_id=current_user.id,  # ID کاربر
    role="user",              # نقش: کاربر
    content=payload.question, # محتوای سوال
)
```

#### 2. پاسخ دستیار (Assistant Message)
بعد از دریافت پاسخ از مدل:
- **ذخیره می‌شود در جدول `messages`**
- **با همان `conversation_id`** که سوال کاربر
- **با `role="assistant"`**
- **با `content`** برابر با پاسخ مدل
- **با همان `user_id`** که سوال کاربر

```python
assistant_msg = Message(
    conversation_id=conv.id,  # همان ID گفتگو
    user_id=current_user.id,  # همان ID کاربر
    role="assistant",         # نقش: دستیار
    content=answer,           # محتوای پاسخ
)
```

### جریان کامل

1. کاربر سوال می‌پرسد → **سوال در دیتابیس ذخیره می‌شود**
2. سیستم تاریخچه گفتگو را می‌خواند
3. سیستم سوال + تاریخچه را به مدل ارسال می‌کند
4. مدل پاسخ می‌دهد → **پاسخ در دیتابیس ذخیره می‌شود**
5. پاسخ به کاربر برگردانده می‌شود

### اطمینان از ذخیره‌سازی

✅ هر دو پیام (سوال و پاسخ) **حتماً** در دیتابیس ذخیره می‌شوند  
✅ هر دو با **همان `conversation_id`** ذخیره می‌شوند  
✅ ترتیب ذخیره‌سازی بر اساس `created_at` حفظ می‌شود  
✅ می‌توانید تمام پیام‌های یک گفتگو را با `GET /conversations/{conversation_id}` مشاهده کنید

### مثال

```json
// سوال اول
{
  "id": 1,
  "conversation_id": 123,
  "user_id": 1,
  "role": "user",
  "content": "قانون مجازات اسلامی چیست؟",
  "created_at": "2024-12-04T10:00:00"
}

// پاسخ اول
{
  "id": 2,
  "conversation_id": 123,  // همان ID
  "user_id": 1,            // همان ID
  "role": "assistant",
  "content": "قانون مجازات اسلامی...",
  "created_at": "2024-12-04T10:00:05"
}

// سوال دوم (در همان گفتگو)
{
  "id": 3,
  "conversation_id": 123,  // همان ID
  "user_id": 1,            // همان ID
  "role": "user",
  "content": "لطفاً خلاصه‌ای بگو",
  "created_at": "2024-12-04T10:01:00"
}

// پاسخ دوم (در همان گفتگو)
{
  "id": 4,
  "conversation_id": 123,  // همان ID
  "user_id": 1,            // همان ID
  "role": "assistant",
  "content": "خلاصه قانون...",
  "created_at": "2024-12-04T10:01:05"
}
```

### بررسی در دیتابیس

می‌توانید با SQL هم بررسی کنید:

```sql
-- مشاهده تمام پیام‌های یک گفتگو
SELECT * FROM messages 
WHERE conversation_id = 123 
ORDER BY created_at ASC;

-- مشاهده سوالات و پاسخ‌های یک گفتگو
SELECT 
    role,
    content,
    created_at
FROM messages 
WHERE conversation_id = 123 
ORDER BY created_at ASC;
```

