from fastapi.testclient import TestClient

from app.main import create_app


def test_health(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app = create_app()
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
