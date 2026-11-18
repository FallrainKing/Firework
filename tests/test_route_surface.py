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
