# استفاده از Python 3.12 slim image برای کاهش حجم
FROM python:3.12-slim

# تنظیم متغیرهای محیطی
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# نصب dependencies سیستم (util-linux برای runuser در entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# ایجاد دایرکتوری کاری و کاربر غیرprivileged قبل از کپی کد
WORKDIR /app
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

# CPU-only torch + constraint so sentence-transformers cannot pull CUDA torch from PyPI
# (that would write libtorch_cuda.so / nvidia_* and fill a small root disk).
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cpu "torch" && \
    python -c "import torch; open('/tmp/torch-constraint.txt','w').write('torch==%s\n'%torch.__version__)" && \
    cat /tmp/torch-constraint.txt && \
    pip install -r requirements.txt -c /tmp/torch-constraint.txt && \
    rm -rf /root/.cache/pip /tmp/* && \
    python -c "import torch; print('torch', torch.__version__); assert '+cpu' in torch.__version__ or not torch.cuda.is_available()"

# کپی کد پروژه (storage/ مدل‌ها و کش HF در .dockerignore هستند)
COPY . .

# دایرکتوری‌های runtime + مالکیت (بدون chown روی گیگابایت کش محلی)
RUN mkdir -p /app/storage/chroma /app/storage/models /app/storage/huggingface /app/data/uploads && \
    chown -R appuser:appuser /app && \
    chmod +x /app/docker-entrypoint.sh

# Entrypoint runs as root briefly to chown mounted volumes, then drops to appuser
USER root
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Command برای اجرای uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
