#!/bin/sh
set -e

# Host-mounted volumes often arrive as root-owned; fix before dropping privileges.
mkdir -p /app/data/uploads \
         /app/storage/chroma \
         /app/storage/models \
         /app/storage/huggingface

chown -R appuser:appuser /app/data /app/storage 2>/dev/null || true

exec runuser -u appuser -- "$@"
