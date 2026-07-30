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


def _blob_looks_valid(path: Path, min_size: int = 1_000_000) -> bool:
    """Reject empty/zero-filled Hugging Face weight blobs."""
    if not path.is_file() or path.stat().st_size < min_size:
        return False
    with path.open("rb") as f:
        head = f.read(4096)
    return any(b != 0 for b in head)


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

    force = __import__("os").environ.get("FORCE_EMBEDDING_DOWNLOAD", "").lower() in {
        "1",
        "true",
        "yes",
    }

    if not Path(model_id).exists():
        from huggingface_hub import snapshot_download

        model_cache = cache_dir / ("models--" + model_id.replace("/", "--"))
        if force and model_cache.exists():
            import shutil

            logging.warning("FORCE_EMBEDDING_DOWNLOAD set — removing corrupt cache: %s", model_cache)
            shutil.rmtree(model_cache, ignore_errors=True)

        logging.info("Downloading model (resume enabled, this may take a while)...")
        local_dir = snapshot_download(
            repo_id=model_id,
            cache_dir=str(cache_dir),
            force_download=force,
            max_workers=2,
        )
        logging.info("Download finished: %s", local_dir)

        weight = Path(local_dir) / "model.safetensors"
        if not weight.exists():
            weight = Path(local_dir) / "pytorch_model.bin"
        if not _blob_looks_valid(weight.resolve() if weight.is_symlink() else weight):
            # On Windows, resolve symlink target for the real blob.
            target = weight
            try:
                target = weight.resolve()
            except OSError:
                pass
            logging.error(
                "Weight file looks corrupt (all-zero or too small): %s (%s bytes). "
                "Re-run with FORCE_EMBEDDING_DOWNLOAD=1 after deleting the model cache.",
                target,
                target.stat().st_size if target.exists() else 0,
            )
            return 1

    from app.services.vectorstore import ensure_embeddings_ready, get_embeddings

    # Clear any previously cached broken handle in this process.
    import app.services.vectorstore as vs

    vs._embeddings_cache = None

    ensure_embeddings_ready()
    emb = get_embeddings()
    a = emb.embed_query("query: divorce check one")
    b = emb.embed_query("query: hello check two")
    cos = sum(x * y for x, y in zip(a, b))
    if cos > 0.999:
        logging.error(
            "Model still returns collapsed embeddings (cos=%.4f). "
            "Delete the model cache under %s and re-run with FORCE_EMBEDDING_DOWNLOAD=1.",
            cos,
            cache_dir,
        )
        return 1
    logging.info("Embedding model loaded successfully (diversity cos=%.4f).", cos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
