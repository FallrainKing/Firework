#!/usr/bin/env python3
"""端到端冒烟测试：对运行中的 compose 服务按顺序验证核心链路。

运行（服务已 `docker compose up -d`）::

    .venv/bin/python scripts/smoke_test.py

步骤（任一步失败 → 打印步骤名并以退出码 1 结束）：
  1. GET  /health           → 200 且 status == "ok"
  2. POST /api/papers/upload → 返回 paper_id（上传 tests/fixtures/sample.pdf）
  3. POST /api/qa           → answer 非空且 citations 非空
  4. POST /api/import/folder → job 轮询至 done（含 1 个好 PDF 的临时目录）

宽容重试：首轮启动时 bge-m3 模型（~2.3GB）在应用首启下载，期间端口未监听或
/api/qa 返回 503/500 —— /health 与 /api/qa 的重试上限 40 次 × 30 秒（20 分钟）。
脚本全程幂等可重跑（重复上传/导入会命中内容去重，job 每次新建）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8600"
REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PDF = REPO_ROOT / "tests" / "fixtures" / "sample.pdf"

# compose 把宿主 ./data 挂载为容器内 /app/data（见 docker-compose.yml），
# 批量导入接口收的是容器内路径，所以临时目录要建在挂载卷里。
HOST_DATA_DIR = REPO_ROOT / "data"
CONTAINER_DATA_DIR = "/app/data"

# 模型下载/服务就绪的宽容窗口：40 次 × 30s = 最长 20 分钟。
READY_ATTEMPTS = 40
READY_INTERVAL_S = 30.0

# 导入 job 轮询：单个 PDF（去重后仅嵌入少量分块）应远快于该窗口。
JOB_TIMEOUT_S = 600.0
JOB_POLL_S = 5.0

HTTP_TIMEOUT = httpx.Timeout(120.0)


def fail(step: str, message: str) -> None:
    print(f"[FAIL] {step}: {message}")
    sys.exit(1)


def step_health(client: httpx.Client) -> None:
    """GET /health → 200 {"status":"ok"}（服务首启下载模型期间端口未就绪，宽容重试）。"""
    last_error = "no attempt made"
    for attempt in range(1, READY_ATTEMPTS + 1):
        try:
            response = client.get("/health", timeout=HTTP_TIMEOUT)
            if response.status_code == 200 and response.json().get("status") == "ok":
                print("[PASS] 1/4 /health 返回 200 ok")
                return
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        print(
            f"      /health 未就绪（第 {attempt}/{READY_ATTEMPTS} 次，{last_error}），"
            f"{READY_INTERVAL_S:.0f}s 后重试…"
        )
        time.sleep(READY_INTERVAL_S)
    fail("step 1 /health", f"重试 {READY_ATTEMPTS} 次后仍未就绪：{last_error}")


def step_upload(client: httpx.Client) -> int:
    """POST /api/papers/upload（multipart 字段名 file）→ paper_id。"""
    if not FIXTURE_PDF.is_file():
        fail("step 2 上传 fixture", f"fixture 不存在：{FIXTURE_PDF}")
    try:
        with FIXTURE_PDF.open("rb") as fh:
            files = {"file": ("sample.pdf", fh, "application/pdf")}
            response = client.post("/api/papers/upload", files=files, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        fail("step 2 上传 PDF", f"网络错误：{exc}")
    if response.status_code != 200:
        fail("step 2 上传 PDF", f"HTTP {response.status_code}: {response.text[:300]}")
    paper_id = response.json().get("paper_id")
    if not isinstance(paper_id, int) or paper_id < 1:
        fail("step 2 上传 PDF", f"响应缺少有效的 paper_id：{response.text[:300]}")
    print(f"[PASS] 2/4 上传 sample.pdf → paper_id={paper_id}")
    return paper_id


def step_qa(client: httpx.Client, paper_id: int) -> None:
    """POST /api/qa → answer 与 citations 均非空（模型未就绪的 503/500 宽容重试）。"""
    payload = {"question": "这篇论文讲了什么", "paper_id": paper_id}
    last_error = "no attempt made"
    for attempt in range(1, READY_ATTEMPTS + 1):
        try:
            response = client.post("/api/qa", json=payload, timeout=HTTP_TIMEOUT)
            if response.status_code == 200:
                body = response.json()
                answer = (body.get("answer") or "").strip()
                citations = body.get("citations")
                if answer and citations:
                    print(
                        f"[PASS] 3/4 /api/qa answer 非空（{len(answer)} 字符），"
                        f"citations {len(citations)} 条（首页：页 {citations[0].get('page')}）"
                    )
                    return
                # 200 但内容为空是真实的检索/索引问题，不算未就绪 → 直接失败
                fail(
                    "step 3 /api/qa",
                    f"HTTP 200 但内容为空：answer={'有' if answer else '空'}, "
                    f"citations={citations}",
                )
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}: {response.text[:200]}（模型/网关可能未就绪）"
            else:
                fail("step 3 /api/qa", f"HTTP {response.status_code}: {response.text[:300]}")
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        print(
            f"      /api/qa 未成功（第 {attempt}/{READY_ATTEMPTS} 次，{last_error}），"
            f"{READY_INTERVAL_S:.0f}s 后重试…"
        )
        time.sleep(READY_INTERVAL_S)
    fail("step 3 /api/qa", f"重试 {READY_ATTEMPTS} 次后仍未成功：{last_error}")


def step_import_folder(client: httpx.Client) -> None:
    """POST /api/import/folder（挂载卷内的临时目录，1 个好 PDF）→ 轮询 job 至 done。"""
    if not FIXTURE_PDF.is_file():
        fail("step 4 批量导入", f"fixture 不存在：{FIXTURE_PDF}")
    HOST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="smoke-import-", dir=HOST_DATA_DIR))
    except PermissionError:
        fail(
            "step 4 批量导入",
            f"{HOST_DATA_DIR} 不可写（docker 首次 up 时以 root 自动创建了该目录）。"
            "修复：宿主机先 mkdir data 再 docker compose up；或对已存在的目录执行"
            " `sg docker -c \"docker compose exec app chown $(id -u):$(id -g) /app/data\"`。",
        )
    container_path = f"{CONTAINER_DATA_DIR}/{tmp_dir.name}"
    try:
        shutil.copy2(FIXTURE_PDF, tmp_dir / "sample.pdf")
        try:
            response = client.post(
                "/api/import/folder", json={"path": container_path}, timeout=HTTP_TIMEOUT
            )
        except httpx.HTTPError as exc:
            fail("step 4 批量导入", f"网络错误：{exc}")
        if response.status_code != 200:
            fail("step 4 批量导入", f"HTTP {response.status_code}: {response.text[:300]}")
        job_id = response.json().get("job_id")
        if job_id is None:
            fail("step 4 批量导入", f"响应缺少 job_id：{response.text[:300]}")

        deadline = time.monotonic() + JOB_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                job = client.get(f"/api/import/jobs/{job_id}", timeout=HTTP_TIMEOUT)
            except httpx.HTTPError as exc:
                fail("step 4 批量导入", f"查询 job {job_id} 失败：{exc}")
            if job.status_code != 200:
                fail("step 4 批量导入", f"查询 job {job_id} 失败：HTTP {job.status_code}")
            body = job.json()
            if body.get("status") == "done":
                done, failed = body.get("done"), body.get("failed")
                if done and not failed:
                    print(f"[PASS] 4/4 批量导入 job {job_id} done（done={done}, failed={failed}）")
                    return
                fail("step 4 批量导入", f"job {job_id} done 但结果异常：{body}")
            time.sleep(JOB_POLL_S)
        fail("step 4 批量导入", f"job {job_id} 在 {JOB_TIMEOUT_S:.0f}s 内未到 done")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    print(f"冒烟测试目标：{BASE_URL}")
    with httpx.Client(base_url=BASE_URL) as client:
        step_health(client)
        paper_id = step_upload(client)
        step_qa(client, paper_id)
        step_import_folder(client)
    print("全部通过：服务健康、上传、问答、批量导入均 OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
