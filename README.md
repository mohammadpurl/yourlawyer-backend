# YourLawyer IR - Backend (FastAPI + LangChain + Chroma)

A Persian legal RAG backend for Iranian laws. Upload PDFs/DOCX/TXT, index to Chroma, and ask questions.

## Quickstart

```bash
# 1) Create venv (Windows PowerShell)
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1

# 2) Install
pip install -r requirements.txt

# 3) Configure (optional)
copy .env.example .env  # then adjust values

# 4) Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open: http://localhost:8000/docs

## Environment

- `CHROMA_DB_DIR`: path to persist Chroma (default: `./storage/chroma`)
- `UPLOAD_DIR`: where uploaded files are saved (default: `./data/uploads`)
- `EMBEDDING_MODEL`: sentence-transformers model (default: `intfloat/multilingual-e5-base`)
- `OPENAI_API_KEY`: if set, uses OpenAI Chat for generation
- `OLLAMA_MODEL`: e.g., `llama3.1:8b` if using local Ollama
- `DEFAULT_TOP_K`: retrieval k (default: 5)
- `CHUNK_SIZE`, `CHUNK_OVERLAP`: splitter settings

## API

- `POST /upload` (multipart): upload files to index
- `GET /stats`: vector store stats
- `POST /ask` JSON `{ question, top_k? }`

If no LLM is configured, it returns an extractive context-based answer as a fallback.

