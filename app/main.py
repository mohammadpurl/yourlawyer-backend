import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.auth import router as auth_router
from app.routes.rag import router as rag_router
from app.routes.conversation import router as conversation_router
from app.core.database import Base, engine
from app.core.logging import configure_logging
from app.core.monitoring import init_sentry

# Import models to ensure they are registered in metadata
import app.models.user  # noqa: F401


configure_logging()
init_sentry()

logger = logging.getLogger("app.main")

app = FastAPI(title="YourLawyer RAG (IR)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(rag_router)
app.include_router(conversation_router)


@app.on_event("startup")
def on_startup_create_tables() -> None:
    # Create all tables if they do not exist
    Base.metadata.create_all(bind=engine)
    logger.info("Startup completed: database tables ensured")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
