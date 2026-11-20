"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient

from .documents.router import router as documents_router
from .imports.router import router as imports_router, internal as imports_internal
from .papers.router import router as papers_router
from .schedules.router import router as schedules_router
from .schedules import service as schedules_service
from .workbench.router import router as workbench_router
from .agent.router import router as agent_router
from .agent import service as agent_service
from .skills.router import router as skills_router
from .users.router import router as users_router
from .frontier.router import router as frontier_router, internal as frontier_internal
from .reader.router import router as reader_router
from .reader.guides.router import router as guide_router,internal as guide_internal
from .sessions.router import router as sessions_router
from .auth.store import AuthStore
from .auth.runtime import WorkspaceManager
from .auth.middleware import AuthenticationMiddleware
from .auth.router import router as auth_router
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
            store = VectorStore(QdrantClient(settings.qdrant_url), collection=settings.vector_collection)
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
    from .documents.service import backfill
    backfill(db, settings)


    embedder, store = await _init_rag_stack(settings)
    app.state.embedder = embedder
    app.state.store = store

    if app.state.authentication:
        app.state.auth_store = AuthStore.from_env(settings.data_dir)
        app.state.workspaces = WorkspaceManager(app)
    agent_service.init_agent_state(app)
    # Stop runner jobs orphaned by a previous app crash/restart (best-effort).
    orphan_cleanup=asyncio.create_task(agent_service.cancel_orphaned_runner_jobs(app.state))
    scheduler=None
    try:
        if app.state.authentication:
            await app.state.workspaces.load_accounts()
        scheduler=asyncio.create_task(schedules_service.schedule_loop(app))
        yield
    finally:
        if scheduler:
            scheduler.cancel()
        orphan_cleanup.cancel()
        await asyncio.gather(*([scheduler] if scheduler else []),orphan_cleanup,return_exceptions=True)
        if app.state.authentication:
            await app.state.workspaces.close()
        await agent_service.close_agent_state(app)
        db.close()
        if app.state.authentication:
            app.state.auth_store.close()


def create_app(*, authentication: bool = True) -> FastAPI:
    """Build the FastAPI app: API routers + health endpoint + static web UI."""
    app = FastAPI(title="Firework", lifespan=lifespan)
    app.state.authentication = authentication
    if authentication:
        app.add_middleware(AuthenticationMiddleware)
    register_error_handlers(app)
    @app.exception_handler(RequestValidationError)
    async def private_validation_errors(request,exc):
        if request.url.path.startswith(('/api/auth/','/api/admin/')):
            # FastAPI's default errors include raw input, which can be a password.
            errors=[{k:e[k] for k in ('loc','msg','type') if k in e} for e in exc.errors()]
            return JSONResponse({'detail':errors},status_code=422)
        return await request_validation_exception_handler(request,exc)
    app.include_router(auth_router)

    app.include_router(agent_router)
    app.include_router(skills_router)
    app.include_router(users_router)
    app.include_router(frontier_router)
    app.include_router(frontier_internal)
    app.include_router(sessions_router)
    app.include_router(papers_router)
    app.include_router(documents_router)
    app.include_router(reader_router)
    app.include_router(guide_router)
    app.include_router(guide_internal)
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
