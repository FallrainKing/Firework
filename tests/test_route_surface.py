"""create_app() must register every domain's routers.

Hand-built test fixtures include routers manually, so a missing
include_router() in main.py is invisible to them — this pins the real
production route surface instead.
"""
from app.main import create_app


def test_create_app_registers_schedule_routes():
    paths = create_app().openapi()['paths']
    assert set(paths['/api/workbench/schedules']) == {'get', 'post'}
    assert set(paths['/api/workbench/schedules/{ident}']) == {'patch'}
    assert set(paths['/api/workbench/schedules/{ident}/run']) == {'post'}


def test_create_app_registers_every_domain():
    paths = create_app().openapi()['paths']
    for p in ('/health', '/api/agent/status', '/api/sessions', '/api/library/papers',
              '/api/reader/papers/{paper_id}', '/api/imports/source',
              '/api/internal/imports/{ident}/execute', '/api/workbench/states/{ident}',
              '/api/workbench/drafts/{sid}/{pid}', '/api/workbench/images'):
        assert p in paths, p


def test_legacy_routes_retired():
    paths = create_app().openapi()['paths']
    for p in paths:
        assert not p.startswith(('/api/qa', '/api/study', '/api/notes', '/api/papers', '/api/import/')), p


def test_v2_mount_when_dist_present(tmp_path, monkeypatch):
    import app.main as main
    (tmp_path / 'index.html').write_text('<html></html>')
    monkeypatch.setattr(main, 'V2_DIR', tmp_path)
    assert '/v2' in [getattr(r, 'path', None) for r in main.create_app().routes]


def test_v2_absent_without_dist(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'V2_DIR', tmp_path / 'missing')
    assert '/v2' not in [getattr(r, 'path', None) for r in main.create_app().routes]


def test_smoke_workspace_step_dry_run(tmp_path, monkeypatch, embedder):
    """The deploy-gate smoke script's workspace step must work against the real app."""
    import importlib.util
    import re
    from pathlib import Path

    from fastapi.testclient import TestClient

    import app.main as main

    script = Path(__file__).resolve().parents[1] / 'scripts' / 'smoke_test.py'
    spec = importlib.util.spec_from_file_location('smoke_test', script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert re.fullmatch(r'[a-f0-9]{32}', mod.PROBE_ID)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('QDRANT_URL', ':memory:')
    monkeypatch.setattr(main, 'Embedder', lambda model_name='BAAI/bge-m3': embedder)
    with TestClient(main.create_app()) as c:
        mod.check_workspace(c)
