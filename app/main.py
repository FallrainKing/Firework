"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient

from . import api
from .config import Settings
from .db import get_conn
from .llm.gateway import LLMGateway
from .rag.embedder import Embedder
from .rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize settings/db/gateway/embedder/store onto ``app.state``.

    The RAG stack failing to initialize — most commonly qdrant being
    unreachable — must not keep the whole application from starting: the
    db and gateway are set up regardless, the broken pieces stay ``None``
    and the routes that need them answer 503 (see
    ``app.api.require_rag_stack``) while health/listing keep working.
    """
    settings = Settings.from_env()
    app.state.settings = settings
    db = get_conn(settings)
    app.state.db = db
    app.state.gateway = LLMGateway(settings)

    embedder = None
    store = None
    try:
        embedder = Embedder()
        store = VectorStore(QdrantClient(settings.qdrant_url))
        store.ensure_collection(embedder.dimension)
    except Exception:
        logger.exception(
            "RAG stack unavailable; /api/qa and the ingest routes will answer 503"
        )
        embedder = None
        store = None
    app.state.embedder = embedder
    app.state.store = store

    try:
        yield
    finally:
        db.close()


def create_app() -> FastAPI:
    """Build the FastAPI app: API routers + health endpoint + static web UI."""
    app = FastAPI(title="Research Assistant", lifespan=lifespan)

    app.include_router(api.papers.router)
    app.include_router(api.qa.router)
    app.include_router(api.imports.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # mounted last so the explicit routes above (and /health) win
    app.mount(
        "/",
        StaticFiles(directory=WEB_DIR, html=True),
        name="web",
    )
    return app


app = create_app()
