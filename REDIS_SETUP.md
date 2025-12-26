# راهنمای نصب و تنظیم Redis

## آیا Redis لازم است؟

**خیر، Redis اختیاری است!** سیستم شما بدون Redis هم کار می‌کند، اما:
- ✅ **با Redis**: عملکرد بهتر (caching فعال)
- ⚠️ **بدون Redis**: سیستم کار می‌کند اما کندتر (caching غیرفعال)

## گزینه 1: استفاده از Docker (توصیه می‌شود)

اگر از `docker-compose.yml` استفاده می‌کنید، Redis به صورت خودکار اضافه شده است:

```bash
# راه‌اندازی همه سرویس‌ها (شامل Redis)
docker-compose up -d

# بررسی وضعیت Redis
docker-compose ps redis

# مشاهده لاگ‌های Redis
docker-compose logs redis
```

## گزینه 2: نصب مستقیم روی سرور

### Ubuntu/Debian:
```bash
sudo apt update
sudo apt install redis-server -y

# راه‌اندازی Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# بررسی وضعیت
redis-cli ping
# باید پاسخ دهد: PONG
```

### CentOS/RHEL:
```bash
sudo yum install epel-release -y
sudo yum install redis -y

# راه‌اندازی Redis
sudo systemctl start redis
sudo systemctl enable redis
```

### macOS:
```bash
brew install redis
brew services start redis
```

## گزینه 3: استفاده از Managed Redis (برای Production)

برای محیط Production، استفاده از سرویس‌های مدیریت‌شده توصیه می‌شود:

- **Redis Cloud**: https://redis.com/cloud/
- **AWS ElastiCache**: برای AWS
- **Azure Cache for Redis**: برای Azure
- **Google Cloud Memorystore**: برای GCP

## تنظیمات

### 1. در فایل `.env`:

```bash
# فعال کردن Redis
REDIS_ENABLED=true

# آدرس Redis
# برای Docker:
REDIS_URL=redis://redis:6379/0

# برای نصب مستقیم:
REDIS_URL=redis://localhost:6379/0

# برای Managed Service (مثال Redis Cloud):
REDIS_URL=redis://username:password@host:port/0
```

### 2. در `docker-compose.yml`:

اگر از Docker استفاده می‌کنید، تنظیمات به صورت خودکار انجام شده است.

## تست اتصال

### از داخل کانتینر/سرور:
```bash
# تست با redis-cli
redis-cli ping
# باید پاسخ دهد: PONG

# یا تست از Python
python -c "import redis; r = redis.from_url('redis://localhost:6379/0'); print(r.ping())"
```

### از کد Python:
```python
from app.core.cache import get_redis_client

client = get_redis_client()
if client:
    print("Redis connected!")
    print(client.ping())
else:
    print("Redis not available")
```

## غیرفعال کردن Redis

اگر نمی‌خواهید از Redis استفاده کنید:

```bash
# در فایل .env
REDIS_ENABLED=false
```

یا در `docker-compose.yml`:
```yaml
environment:
  REDIS_ENABLED: "false"
```

در این حالت، سیستم بدون cache کار می‌کند اما همه چیز به درستی عمل می‌کند.

## بررسی عملکرد Cache

برای بررسی اینکه cache کار می‌کند:

1. یک سوال بپرسید (اولین بار - cache miss)
2. همان سوال را دوباره بپرسید (دومین بار - cache hit، باید سریع‌تر باشد)

در لاگ‌ها باید پیام `Cache hit for question: ...` را ببینید.

## عیب‌یابی

### مشکل: "Redis not available"
- بررسی کنید Redis نصب و در حال اجرا است
- بررسی کنید `REDIS_URL` درست است
- بررسی کنید firewall پورت 6379 را باز کرده است

### مشکل: "Connection refused"
- Redis در حال اجرا نیست: `sudo systemctl start redis`
- پورت اشتباه است: بررسی `REDIS_URL`

### مشکل: "Authentication required"
- اگر Redis password دارد، باید در URL باشد:
  `redis://:password@host:6379/0`

## منابع

- مستندات Redis: https://redis.io/documentation
- Python Redis Client: https://redis-py.readthedocs.io/


