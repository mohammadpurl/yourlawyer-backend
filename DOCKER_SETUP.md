# راهنمای راه‌اندازی با Docker

## پیش‌نیازها

- Docker (version 20.10 یا بالاتر)
- Docker Compose (version 1.29 یا بالاتر)

## نصب و راه‌اندازی

### 1. کلون پروژه (اگر از Git استفاده می‌کنید)

```bash
git clone <repository-url>
cd your-lowyer-back
```

### 2. تنظیم متغیرهای محیطی

فایل `.env` را از `.env.example` بسازید:

```bash
cp .env.example .env
```

سپس فایل `.env` را ویرایش کنید و مقادیر را تنظیم کنید:

```env
# مهم: SECRET_KEY را تغییر دهید
SECRET_KEY=your-secret-key-here

# اگر از OpenAI استفاده می‌کنید
OPENAI_API_KEY=your-openai-api-key
```

### 3. ساخت و راه‌اندازی

```bash
# ساخت image و راه‌اندازی همه سرویس‌ها
docker-compose up -d --build
```

### 4. بررسی وضعیت

```bash
# مشاهده لاگ‌ها
docker-compose logs -f

# مشاهده وضعیت سرویس‌ها
docker-compose ps
```

### 5. تست API

```bash
# Health check
curl http://localhost:8000/health

# یا در مرورگر
open http://localhost:8000/docs
```

## دستورات مفید

### توقف سرویس‌ها

```bash
docker-compose stop
```

### شروع مجدد

```bash
docker-compose start
```

### توقف و حذف containers

```bash
docker-compose down
```

### توقف و حذف containers + volumes (⚠️ تمام داده‌ها حذف می‌شود)

```bash
docker-compose down -v
```

### مشاهده لاگ‌های یک سرویس خاص

```bash
# لاگ‌های API
docker-compose logs -f api

# لاگ‌های Database
docker-compose logs -f db
```

### اجرای دستورات در container

```bash
# دسترسی به shell داخل container
docker-compose exec api bash

# اجرای یک دستور خاص
docker-compose exec api python -m pytest
```

### Rebuild فقط یک سرویس

```bash
docker-compose build api
docker-compose up -d api
```

## Volume ها

داده‌های زیر به صورت persistent نگهداری می‌شوند:

- **postgres_data**: داده‌های PostgreSQL
- **chroma_data**: داده‌های ChromaDB (vectorstore)
- **uploads_data**: فایل‌های آپلود شده
- **app_storage**: فایل‌های storage دیگر

### Backup Volume ها

```bash
# Backup PostgreSQL
docker run --rm -v yourlawyer_postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres_backup.tar.gz -C /data .

# Backup ChromaDB
docker run --rm -v yourlawyer_chroma_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/chroma_backup.tar.gz -C /data .
```

### Restore Volume ها

```bash
# Restore PostgreSQL
docker run --rm -v yourlawyer_postgres_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/postgres_backup.tar.gz -C /data

# Restore ChromaDB
docker run --rm -v yourlawyer_chroma_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/chroma_backup.tar.gz -C /data
```

## تنظیمات پیشرفته

### تغییر Port ها

در فایل `.env`:

```env
API_PORT=8080
POSTGRES_PORT=5433
```

### استفاده از PostgreSQL خارجی

اگر می‌خواهید از PostgreSQL خارج از Docker استفاده کنید:

1. سرویس `db` را از `docker-compose.yml` حذف کنید
2. در `.env` مقدار `DATABASE_URL` را تنظیم کنید:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname
```

3. `depends_on` را از سرویس `api` حذف کنید

### استفاده از Production Environment

برای production:

1. **SECRET_KEY** قوی تولید کنید:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **DATABASE_PASSWORD** قوی تنظیم کنید

3. CORS origins را محدود کنید (در `app/main.py`)

4. از reverse proxy مثل Nginx استفاده کنید

5. SSL/TLS را فعال کنید

## عیب‌یابی

### Container راه‌اندازی نمی‌شود

```bash
# بررسی لاگ‌ها
docker-compose logs api

# بررسی وضعیت
docker-compose ps

# Rebuild
docker-compose build --no-cache api
```

### خطای اتصال به Database

```bash
# بررسی سلامت database
docker-compose exec db pg_isready -U postgres

# بررسی اتصال
docker-compose exec api python -c "from app.core.database import engine; engine.connect()"
```

### خطای Port در حال استفاده

```bash
# بررسی port استفاده شده
netstat -tulpn | grep 8000

# تغییر port در .env
API_PORT=8080
```

### حذف همه چیز و شروع مجدد

```bash
# ⚠️ تمام داده‌ها حذف می‌شود
docker-compose down -v
docker system prune -a
docker-compose up -d --build
```

## ساختار Docker

```
your-lowyer-back/
├── Dockerfile              # Docker image definition
├── docker-compose.yml      # Docker Compose configuration
├── .dockerignore           # Files to ignore in Docker build
├── .env.example            # Example environment variables
└── .env                    # Your environment variables (not in git)
```

## Performance Tips

1. **برای Production**: از multi-stage build استفاده کنید
2. **Caching**: لایه‌های Docker را بهینه کنید
3. **Resources**: محدودیت‌های CPU و Memory را تنظیم کنید:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

## امنیت

1. ✅ از `.env` برای secrets استفاده کنید (و در Git commit نکنید)
2. ✅ SECRET_KEY قوی تولید کنید
3. ✅ Database password قوی تنظیم کنید
4. ✅ CORS origins را محدود کنید
5. ✅ از HTTPS در production استفاده کنید
6. ✅ Docker images را به‌روز نگه دارید

