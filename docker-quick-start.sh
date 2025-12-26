#!/bin/bash

# اسکریپت راه‌اندازی سریع Docker

echo "🚀 راه‌اندازی YourLawyer Backend با Docker..."

# بررسی وجود .env
if [ ! -f .env ]; then
    echo "📝 ایجاد فایل .env از .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "⚠️  لطفاً فایل .env را ویرایش کنید و SECRET_KEY را تغییر دهید!"
    else
        echo "❌ فایل .env.example پیدا نشد. لطفاً دستی ایجاد کنید."
        exit 1
    fi
fi

# ساخت و راه‌اندازی
echo "🔨 ساخت Docker images..."
docker-compose build

echo "🚀 راه‌اندازی containers..."
docker-compose up -d

echo "⏳ منتظر راه‌اندازی سرویس‌ها..."
sleep 10

# بررسی سلامت
echo "🏥 بررسی سلامت API..."
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ API در حال اجرا است!"
    echo "📚 مستندات API: http://localhost:8000/docs"
else
    echo "⚠️  API هنوز آماده نیست. لطفاً لاگ‌ها را بررسی کنید:"
    echo "   docker-compose logs -f api"
fi

echo ""
echo "📋 دستورات مفید:"
echo "   مشاهده لاگ‌ها: docker-compose logs -f"
echo "   توقف: docker-compose stop"
echo "   حذف: docker-compose down"
echo "   مشاهده وضعیت: docker-compose ps"

