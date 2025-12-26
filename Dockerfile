# استفاده از Python 3.12 slim image برای کاهش حجم
FROM python:3.12-slim

# تنظیم متغیرهای محیطی
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# نصب dependencies سیستم
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ایجاد دایرکتوری کاری
WORKDIR /app

# کپی requirements.txt و نصب dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# کپی کد پروژه
COPY . .

# ایجاد دایرکتوری‌های لازم برای storage
RUN mkdir -p /app/storage/chroma /app/data/uploads /app/storage

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Command برای اجرای uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]

