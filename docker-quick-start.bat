@echo off
REM اسکریپت راه‌اندازی سریع Docker برای Windows

echo 🚀 راه‌اندازی YourLawyer Backend با Docker...

REM بررسی وجود .env
if not exist .env (
    echo 📝 ایجاد فایل .env از .env.example...
    if exist .env.example (
        copy .env.example .env
        echo ⚠️  لطفاً فایل .env را ویرایش کنید و SECRET_KEY را تغییر دهید!
    ) else (
        echo ❌ فایل .env.example پیدا نشد. لطفاً دستی ایجاد کنید.
        exit /b 1
    )
)

REM ساخت و راه‌اندازی
echo 🔨 ساخت Docker images...
docker-compose build

echo 🚀 راه‌اندازی containers...
docker-compose up -d

echo ⏳ منتظر راه‌اندازی سرویس‌ها...
timeout /t 10 /nobreak > nul

REM بررسی سلامت
echo 🏥 بررسی سلامت API...
curl -f http://localhost:8000/health > nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ API در حال اجرا است!
    echo 📚 مستندات API: http://localhost:8000/docs
) else (
    echo ⚠️  API هنوز آماده نیست. لطفاً لاگ‌ها را بررسی کنید:
    echo    docker-compose logs -f api
)

echo.
echo 📋 دستورات مفید:
echo    مشاهده لاگ‌ها: docker-compose logs -f
echo    توقف: docker-compose stop
echo    حذف: docker-compose down
echo    مشاهده وضعیت: docker-compose ps

pause

