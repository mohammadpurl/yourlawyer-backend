import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

# Storage directories
PERSIST_DIRECTORY = Path(
    os.getenv("CHROMA_DB_DIR", BASE_DIR / "storage" / "chroma")
).as_posix()
UPLOAD_DIRECTORY = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)

# Embedding model
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")

# LLM selection
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")  # e.g., "llama3.1:8b"

# Retrieval defaults
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
