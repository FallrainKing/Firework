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


def test_health_stays_responsive_during_slow_parse(
    api_client, sample_pdf, tmp_path, monkeypatch
):
    """The heavy parse/embed runs on a worker thread (asyncio.to_thread), so
    the event loop keeps answering while a background import parses."""
    import app.ingest.pipeline as pipeline

    real_extract = pipeline.extract_pages

    def slow_extract(pdf_path):
        time.sleep(2.0)  # pathological PDF: parsing takes seconds
        return real_extract(pdf_path)

    monkeypatch.setattr(pipeline, "extract_pages", slow_extract)

    folder = tmp_path / "slowpdfs"
    folder.mkdir()
    shutil.copy(sample_pdf, folder / "slow.pdf")
    with api_client(FakeGateway()) as client:
        r = client.post("/api/import/folder", json={"path": str(folder)})
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]

        # poll while the job parses: every /health call must stay well
        # under the 2s parse sleep — with the old loop-blocking code each
        # call stalled for the whole parse instead
        worst = 0.0
        polls = 0
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            health = client.get("/health")
            worst = max(worst, time.monotonic() - t0)
            polls += 1
            assert health.status_code == 200
            if client.get(f"/api/import/jobs/{job_id}").json()["status"] == "done":
                break
            time.sleep(0.05)

        assert polls >= 3, "job finished before responsiveness could be observed"
        assert worst < 1.0, f"/health blocked {worst:.2f}s during the import"
