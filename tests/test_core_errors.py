"""Core error infrastructure: ServiceError responses must match HTTPException exactly."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def test_service_error_response_matches_http_exception():
    from app.core.errors import ServiceError, register_error_handlers

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/svc")
    def svc():
        raise ServiceError(409, "冲突文案")

    @app.get("/http")
    def http():
        raise HTTPException(409, "冲突文案")

    client = TestClient(app)
    a, b = client.get("/svc"), client.get("/http")
    assert a.status_code == b.status_code == 409
    assert a.json() == b.json() == {"detail": "冲突文案"}


def test_create_app_registers_service_error_handler():
    from app.core.errors import ServiceError
    from app.main import create_app

    assert ServiceError in create_app().exception_handlers


def test_migrations_dir_resolves():
    from app.core.db import MIGRATIONS_DIR

    assert MIGRATIONS_DIR.is_dir()
    assert len(list(MIGRATIONS_DIR.glob("*.sql"))) >= 7


def test_fresh_db_applies_all_migrations(tmp_path):
    from app.core.config import Settings
    from app.core.db import MIGRATIONS_DIR, get_conn

    db = get_conn(Settings(data_dir=tmp_path, qdrant_url="unused"))
    try:
        applied = db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        assert applied == len(list(MIGRATIONS_DIR.glob("*.sql")))
    finally:
        db.close()
