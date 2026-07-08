"""
Download and verify the embedding model for bulk ingest.

Uses standard HTTP download (XET disabled) and stores cache on drive D
under storage/huggingface by default.

Usage:
    python scripts/download_embedding_model.py

Optional env vars:
    HF_ENDPOINT=https://hf-mirror.com   # mirror if huggingface.co is blocked
    HF_HOME=D:/path/to/cache
    EMBEDDING_MODEL=intfloat/multilingual-e5-base
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.config import DEFAULT_EMBEDDING_MODEL, EMBEDDING_MODEL, HF_HOME  # noqa: E402


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def main() -> int:
    configure_logging()

    model_id = EMBEDDING_MODEL
    if Path(model_id).exists():
        logging.info("Using local embedding model path: %s", model_id)
    else:
        model_id = DEFAULT_EMBEDDING_MODEL

    cache_dir = HF_HOME / "hub"
    cache_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Model: %s", model_id)
    logging.info("Cache: %s", cache_dir)
    logging.info("HF_HOME: %s", HF_HOME)
    logging.info("HF_ENDPOINT: %s", __import__("os").environ.get("HF_ENDPOINT", "(default)"))
    logging.info("HF_HUB_DISABLE_XET: %s", __import__("os").environ.get("HF_HUB_DISABLE_XET", "0"))

    if not Path(model_id).exists():
        from huggingface_hub import snapshot_download

        logging.info("Downloading model (resume enabled, this may take a while)...")
        snapshot_download(
            repo_id=model_id,
            cache_dir=str(cache_dir),
            resume_download=True,
            max_workers=4,
        )
        logging.info("Download finished.")

    from app.services.vectorstore import ensure_embeddings_ready

    ensure_embeddings_ready()
    logging.info("Embedding model loaded successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
