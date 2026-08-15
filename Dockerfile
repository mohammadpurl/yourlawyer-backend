# ---- deps (compiler discarded after this stage) ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

WORKDIR /build
COPY requirements.txt .

# CPU-only torch + constraint so PyPI cannot pull CUDA torch (multi-GB nvidia_*)
RUN pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cpu "torch" && \
    python -c "import torch; open('/tmp/torch-constraint.txt','w').write('torch==%s\n'%torch.__version__)" && \
    pip install -r requirements.txt -c /tmp/torch-constraint.txt && \
    find /opt/venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyc' -delete 2>/dev/null || true

# ---- runtime ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv
COPY . .

# Do NOT chown -R /app: on servers, large chroma_backup*/chroma_storage trees may
# still sneak into context and exhaust disk during recursive chown.
RUN mkdir -p /app/storage/chroma /app/storage/models /app/storage/huggingface /app/data/uploads && \
    chown -R appuser:appuser \
      /app/app \
      /app/scripts \
      /app/docker-entrypoint.sh \
      /app/storage \
      /app/data \
      /opt/venv && \
    chmod +x /app/docker-entrypoint.sh && \
    python -c "import torch; print('torch', torch.__version__); assert not torch.cuda.is_available()"

USER root
ENTRYPOINT ["/app/docker-entrypoint.sh"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
