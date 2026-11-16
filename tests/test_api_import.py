"""API tests for the folder-import routes and the background batch job."""

from __future__ import annotations

import shutil
import time

import pytest
from conftest import FakeGateway


def _make_folder(tmp_path, sample_pdf):
    """A folder with 2 good PDFs (copies of sample.pdf) and 1 broken one."""
    folder = tmp_path / "pdfs"
    folder.mkdir()
    shutil.copy(sample_pdf, folder / "good1.pdf")
    shutil.copy(sample_pdf, folder / "good2.pdf")
    (folder / "bad.pdf").write_text("not a pdf")
    return folder


def _wait_for_job(client, job_id: int, timeout: float = 120.0) -> dict:
    """Poll the job endpoint until status flips to done (the batch task runs
    on the TestClient's background portal loop while the test thread sleeps)."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = client.get(f"/api/import/jobs/{job_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] == "done":
            return last
        time.sleep(0.05)
    pytest.fail(f"import job {job_id} did not finish in {timeout}s: {last}")


def test_import_path_outside_allowed_rejected(api_client):
    with api_client(FakeGateway()) as client:
        r = client.post(
            "/api/import/folder", json={"path": "/definitely/not/a/real/dir"}
        )
        assert r.status_code == 400
        assert "path" in r.json()["detail"].lower()


def test_batch_import_job_progress(api_client, sample_pdf, tmp_path):
    """2 good + 1 broken PDF → done==2, failed==1, errors names the bad file."""
    folder = _make_folder(tmp_path, sample_pdf)
    with api_client(FakeGateway()) as client:
        r = client.post("/api/import/folder", json={"path": str(folder)})
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]

        job = _wait_for_job(client, job_id)
        assert job["id"] == job_id
        assert job["total"] == 3
        assert job["done"] == 2
        assert job["failed"] == 1
        assert [e["file"] for e in job["errors"]] == ["bad.pdf"]
        assert job["errors"][0]["error"]  # the failure reason is kept too


def test_batch_skips_bad_file(api_client, sample_pdf, tmp_path):
    """The broken file never reaches the library; both good files do, exactly once."""
    folder = _make_folder(tmp_path, sample_pdf)
    with api_client(FakeGateway()) as client:
        r = client.post("/api/import/folder", json={"path": str(folder)})
        assert r.status_code == 200
        _wait_for_job(client, r.json()["job_id"])

        papers = client.get("/api/papers").json()["papers"]
        titles = sorted(p["title"] for p in papers)
        # fallback metadata derives titles from the filenames, and the two
        # copies must NOT have been deduped against each other
        assert titles == ["good1", "good2"]


def test_import_job_not_found_returns_404(api_client):
    with api_client(FakeGateway()) as client:
        r = client.get("/api/import/jobs/999")
        assert r.status_code == 404
