"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient

from . import api
from .api import agent, sessions, library
from .config import Settings
from .db import get_conn
from .llm.gateway import LLMGateway
from .rag.embedder import Embedder
from .rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"

# Bounded startup retry for the RAG stack (qdrant being unreachable at boot
# is normally a race with the container starting). 10 attempts × 10s covers
# ~100s of qdrant slowness; after that we raise so the container's restart
# policy (unless-stopped) takes over instead of the app limping along in a
# permanently degraded, 503-everywhere state.
RAG_STARTUP_ATTEMPTS = 10
RAG_STARTUP_BACKOFF_S = 10.0


async def _init_rag_stack(settings: Settings) -> tuple[Embedder, VectorStore]:
    """Build the embedder + vector store, retrying connection failures.

    The (heavy) embedder is built once and kept across attempts, so qdrant
    retries do not reload the model. ``QdrantClient``/``VectorStore`` are
    rebuilt per attempt — a failed client may hold a dead connection pool.
    Retries exhausted → ``RuntimeError`` (see module note above).
    """
    embedder: Embedder | None = None
    last_error: Exception | None = None
    for attempt in range(1, RAG_STARTUP_ATTEMPTS + 1):
        try:
            if embedder is None:
                embedder = Embedder()
            store = VectorStore(QdrantClient(settings.qdrant_url))
            store.ensure_collection(embedder.dimension)
            return embedder, store
        except Exception as exc:  # noqa: BLE001 — retried, then re-raised below
            last_error = exc
            logger.warning(
                "RAG stack init attempt %d/%d failed: %s",
                attempt,
                RAG_STARTUP_ATTEMPTS,
                exc,
            )
            if attempt < RAG_STARTUP_ATTEMPTS:
                await asyncio.sleep(RAG_STARTUP_BACKOFF_S)
    raise RuntimeError(
        f"RAG stack failed to initialize after {RAG_STARTUP_ATTEMPTS} attempts "
        f"(qdrant at {settings.qdrant_url!r} unreachable?); aborting startup so "
        "the container restart policy can recover"
    ) from last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize settings/db/gateway/embedder/store onto ``app.state``."""
    settings = Settings.from_env()
    app.state.settings = settings
    db = get_conn(settings)
    app.state.db = db
    app.state.gateway = LLMGateway(settings)

    # Startup sweep: jobs a previous (crashed/restarted) process left
    # pending/running can never finish in this process — mark them failed
    # so pollers see the truth instead of a job "running" forever.
    db.execute(
        "UPDATE import_jobs SET status='failed' WHERE status IN ('pending','running')"
    )
    db.commit()

    embedder, store = await _init_rag_stack(settings)
    app.state.embedder = embedder
    app.state.store = store

    agent.init_agent_state(app)
    try:
        yield
    finally:
        await agent.close_agent_state(app)
        db.close()


def create_app() -> FastAPI:
    """Build the FastAPI app: API routers + health endpoint + static web UI."""
    app = FastAPI(title="Research Assistant", lifespan=lifespan)

    app.include_router(api.papers.router)
    app.include_router(api.notes.router)
    app.include_router(api.qa.router)
    app.include_router(api.imports.router)
    app.include_router(api.study.router)
    app.include_router(agent.router)
    app.include_router(sessions.router)
    app.include_router(library.router)

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
