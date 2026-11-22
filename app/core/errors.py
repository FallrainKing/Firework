"""Service-layer errors.

Services raise ``ServiceError`` instead of FastAPI's ``HTTPException`` so the
business layer stays framework-free. The registered handler renders exactly
the same ``{"detail": ...}`` JSON shape and status code, so API behavior is
unchanged.
"""

from __future__ import annotations


class ServiceError(Exception):
    """A business-rule failure carrying the HTTP status and detail to render."""

    def __init__(self, status: int, detail: str, *, code: str | None = None):
        super().__init__(detail)
        self.code = code
        self.status = status
        self.detail = detail


def register_error_handlers(app) -> None:
    from fastapi.responses import JSONResponse

    @app.exception_handler(ServiceError)
    async def _handle(request, exc):
        return JSONResponse({"detail": exc.detail, **({"code": exc.code} if exc.code else {})}, status_code=exc.status)
