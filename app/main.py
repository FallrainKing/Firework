"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app() -> FastAPI:
    """Build the FastAPI app: health endpoint + static web UI at ``/``."""
    app = FastAPI(title="Research Assistant")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.mount(
        "/",
        StaticFiles(directory=WEB_DIR, html=True),
        name="web",
    )
    return app


app = create_app()
