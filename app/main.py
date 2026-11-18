"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient

from .imports.router import router as imports_router, internal as imports_internal
from .papers.router import router as papers_router
from .schedules.router import router as schedules_router
from .schedules import service as schedules_service
from .workbench.router import router as workbench_router
from .agent.router import router as agent_router
from .agent import service as agent_service
from .reader.router import router as reader_router
from .sessions.router import router as sessions_router
from .core.config import Settings
from .core.db import get_conn
from .core.errors import register_error_handlers
from .rag.embedder import Embedder
from .rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
# Vue 工作台构建产物（frontend/ → vite build → app/web/，Docker 多阶段构建拷入；
# 本地开发手动拷贝 dist）。vendor/（PDF.js）保留在仓库中。


class SPAStaticFiles(StaticFiles):
    """Static files with SPA fallback: extension-less 404s serve index.html."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise

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
    """Initialize settings/db/embedder/store onto ``app.state``."""
    settings = Settings.from_env()
    app.state.settings = settings
    db = get_conn(settings)
    app.state.db = db


    embedder, store = await _init_rag_stack(settings)
    app.state.embedder = embedder
    app.state.store = store

    agent_service.init_agent_state(app)
    # Stop runner jobs orphaned by a previous app crash/restart (best-effort).
    orphan_cleanup=asyncio.create_task(agent_service.cancel_orphaned_runner_jobs(app.state))
    try:
        scheduler=asyncio.create_task(schedules_service.schedule_loop(app))
        yield
    finally:
        scheduler.cancel()
        orphan_cleanup.cancel()
        await asyncio.gather(scheduler,orphan_cleanup,return_exceptions=True)
        await agent_service.close_agent_state(app)
        db.close()


def create_app() -> FastAPI:
    """Build the FastAPI app: API routers + health endpoint + static web UI."""
    app = FastAPI(title="Research Assistant", lifespan=lifespan)
    register_error_handlers(app)

    app.include_router(agent_router)
    app.include_router(sessions_router)
    app.include_router(papers_router)
    app.include_router(reader_router)
    app.include_router(imports_router)
    app.include_router(imports_internal)
    app.include_router(workbench_router)
    app.include_router(schedules_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # mounted last so the explicit routes above (and /health) win
    app.mount(
        "/",
        SPAStaticFiles(directory=WEB_DIR, html=True),
        name="web",
    )
    return app


app = create_app()
