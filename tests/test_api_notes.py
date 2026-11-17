"""API tests for the note routes (list / create / delete).

The lifespan's sqlite connection belongs to TestClient's worker thread, so
the tests seed/verify rows through a second connection opened in the test
thread against the same db file (WAL allows the concurrent access); all
route-level db access goes through HTTP only.
"""

from __future__ import annotations

import sqlite3

from conftest import FakeGateway


def _seed_db(tmp_path) -> sqlite3.Connection:
    """A test-thread connection to the same app.db the lifespan opened."""
    conn = sqlite3.connect(tmp_path / "app.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _add_paper(conn, title: str = "Note Host Paper") -> int:
    cur = conn.execute(
        "INSERT INTO papers (title, source, status) VALUES (?, 'upload', 'new')",
        (title,),
    )
    conn.commit()
    return cur.lastrowid


def test_list_notes_empty_then_populated(api_client, tmp_path):
    """A paper with no notes lists []; after inserting two notes the newest
    comes first (created_at DESC) and rows expose the expected fields."""
    with api_client(FakeGateway()) as client:
        conn = _seed_db(tmp_path)
        paper_id = _add_paper(conn)

        r = client.get(f"/api/papers/{paper_id}/notes")
        assert r.status_code == 200, r.text
        assert r.json() == {"notes": []}

        conn.executemany(
            "INSERT INTO notes (paper_id, note_type, content, created_at)"
            " VALUES (?, ?, ?, ?)",
            [
                (paper_id, "annotation", "earlier note", "2026-11-17 09:00:00"),
                (paper_id, "chat_summary", "later note", "2026-11-17 10:00:00"),
            ],
        )
        conn.commit()

        notes = client.get(f"/api/papers/{paper_id}/notes").json()["notes"]
        assert [n["content"] for n in notes] == ["later note", "earlier note"]
        for note in notes:
            assert set(note) == {"id", "paper_id", "note_type", "content", "created_at"}
            assert note["paper_id"] == paper_id


def test_create_note_returns_note_id(api_client, tmp_path):
    """POST a valid annotation → 200 {"note_id": int}; GET lists the row."""
    with api_client(FakeGateway()) as client:
        paper_id = _add_paper(_seed_db(tmp_path))
        r = client.post(
            f"/api/papers/{paper_id}/notes",
            json={"note_type": "annotation", "content": "key insight"},
        )
        assert r.status_code == 200, r.text
        note_id = r.json()["note_id"]
        assert isinstance(note_id, int)

        stored = client.get(f"/api/papers/{paper_id}/notes").json()["notes"]
        assert len(stored) == 1
        assert stored[0]["id"] == note_id
        assert stored[0]["note_type"] == "annotation"
        assert stored[0]["content"] == "key insight"
        assert stored[0]["created_at"]


def test_create_note_invalid_type_returns_400(api_client, tmp_path):
    """A note_type outside the allowed set is a 400, not a 500."""
    with api_client(FakeGateway()) as client:
        paper_id = _add_paper(_seed_db(tmp_path))
        r = client.post(
            f"/api/papers/{paper_id}/notes",
            json={"note_type": "highlight", "content": "nope"},
        )
        assert r.status_code == 400
        assert "note_type" in r.json()["detail"]


def test_create_note_missing_paper_returns_404(api_client, tmp_path):
    """Creating a note for a paper that does not exist answers 404."""
    with api_client(FakeGateway()) as client:
        _seed_db(tmp_path)  # migrations applied, but no papers
        r = client.post(
            "/api/papers/99999/notes",
            json={"note_type": "annotation", "content": "orphan"},
        )
        assert r.status_code == 404


def test_delete_note_returns_deleted(api_client, tmp_path):
    """DELETE an existing note → {"deleted": true}; the list is empty after."""
    with api_client(FakeGateway()) as client:
        paper_id = _add_paper(_seed_db(tmp_path))
        note_id = client.post(
            f"/api/papers/{paper_id}/notes",
            json={"note_type": "chat_summary", "content": "temp"},
        ).json()["note_id"]

        r = client.delete(f"/api/notes/{note_id}")
        assert r.status_code == 200, r.text
        assert r.json() == {"deleted": True}
        assert client.get(f"/api/papers/{paper_id}/notes").json()["notes"] == []


def test_delete_missing_note_returns_404(api_client, tmp_path):
    """Deleting a note that does not exist answers 404."""
    with api_client(FakeGateway()) as client:
        _seed_db(tmp_path)
        r = client.delete("/api/notes/99999")
        assert r.status_code == 404
