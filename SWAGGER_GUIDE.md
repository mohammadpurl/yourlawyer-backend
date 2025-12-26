# راهنمای استفاده از Swagger UI برای تست API

## مشکل قبلی
قبلاً Swagger UI دکمه "Authorize" داشت که از username/password استفاده می‌کرد، اما سیستم ما با OTP و موبایل لاگین می‌کند.

## راه‌حل
حالا Swagger UI برای Bearer Token تنظیم شده است.

## نحوه استفاده

### 1. دریافت توکن (OTP Login)

#### گام 1: ارسال OTP
در Swagger UI:
- به endpoint `POST /auth/otp/send` بروید
- روی "Try it out" کلیک کنید
- در body، شماره موبایل خود را وارد کنید:
```json
{
  "mobile": "09123456789"
}
```
- روی "Execute" کلیک کنید
- OTP در لاگ سرور نمایش داده می‌شود (برای تست)

#### گام 2: تایید OTP و دریافت توکن
- به endpoint `POST /auth/otp/verify` بروید
- روی "Try it out" کلیک کنید
- در body، شماره موبایل و کد OTP را وارد کنید:
```json
{
  "mobile": "09123456789",
  "code": "12345"
}
```
- روی "Execute" کلیک کنید
- در پاسخ، `accessToken` را کپی کنید:
```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "sessionId": "...",
  "sessionExpiry": 1234567890
}
```

### 2. استفاده از توکن در Swagger UI

#### گام 3: وارد کردن توکن
1. در بالای صفحه Swagger UI، روی دکمه **"Authorize"** (یا قفل 🔒) کلیک کنید
2. در قسمت "Bearer", فیلد "Value" را پیدا کنید
3. توکن `accessToken` که در مرحله قبل کپی کردید را در این فیلد وارد کنید
   - **نکته**: فقط مقدار توکن را وارد کنید، نیازی به کلمه "Bearer" نیست
   - مثال: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`
4. روی "Authorize" کلیک کنید
5. سپس روی "Close" کلیک کنید

#### گام 4: تست API های محافظت شده
حالا می‌توانید تمام API های که نیاز به authentication دارند را تست کنید:
- `GET /conversations` - لیست گفتگوها
- `POST /conversations` - ایجاد گفتگو جدید
- `GET /conversations/{conversation_id}` - جزئیات گفتگو
- `POST /conversations/{conversation_id}/ask` - ارسال سوال
- `PUT /auth/me` - به‌روزرسانی پروفایل

### 3. نکات مهم

- ✅ توکن برای مدت محدودی معتبر است (به صورت پیش‌فرض 60 دقیقه)
- ✅ اگر توکن منقضی شد، دوباره از مرحله 1 شروع کنید
- ✅ توکن به صورت خودکار در تمام درخواست‌های بعدی استفاده می‌شود
- ✅ برای حذف توکن، دوباره روی "Authorize" کلیک کنید و "Logout" را بزنید

### 4. مثال کامل

```
1. POST /auth/otp/send → {"mobile": "09123456789"}
   Response: {"sent": {"12345"}}

2. POST /auth/otp/verify → {"mobile": "09123456789", "code": "12345"}
   Response: {
     "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
     "sessionId": "abc123",
     "sessionExpiry": 1733456789
   }

3. در Swagger UI روی "Authorize" کلیک کنید
   در فیلد Bearer: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

4. حالا می‌توانید API های محافظت شده را تست کنید:
   - POST /conversations → ایجاد گفتگو
   - POST /conversations/1/ask → ارسال سوال
```

## عیب‌یابی

### مشکل: "401 Unauthorized"
- ✅ مطمئن شوید توکن را درست وارد کرده‌اید
- ✅ بررسی کنید توکن منقضی نشده باشد
- ✅ دوباره لاگین کنید و توکن جدید بگیرید

### مشکل: دکمه Authorize وجود ندارد
- ✅ مطمئن شوید سرور را restart کرده‌اید
- ✅ به آدرس `http://localhost:8000/docs` بروید

