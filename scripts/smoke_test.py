#!/usr/bin/env python3
"""端到端冒烟测试：对运行中的 compose 服务按顺序验证核心链路。

运行（服务已 `docker compose up -d`）::

    .venv/bin/python scripts/smoke_test.py

步骤（任一步失败 → 打印步骤名并以退出码 1 结束）：
  1. GET  /health           → 200 且 status == "ok"
  2. POST /api/papers/upload → 返回 paper_id（上传 tests/fixtures/sample.pdf）
  3. POST /api/qa           → answer 非空且 citations 非空
  4. POST /api/import/folder → job 轮询至 done（含 1 个好 PDF 的临时目录）
  5. POST /api/papers/{id}/notes（content 含 <script>alert(1)</script>）
                               → GET notes 原样返回（API 层不转义不解析）→ DELETE 清理
  6. POST /api/papers/{id}/interpret → 轮询 job 至 done（真实 LLM，分钟级）
                               → GET notes 出现非空 six_dim
  7. POST /api/compare（2 个已存在 id）→ matrix 非空且 citations 非空

宽容重试：首轮启动时 bge-m3 模型（~2.3GB）在应用首启下载，期间端口未监听或
/api/qa 返回 503/500 —— /health 与 /api/qa 的重试上限 40 次 × 30 秒（20 分钟）；
步骤 6 的 interpret 同样按 40×30s 宽容（真实 LLM 逐节解读是分钟级操作）。
脚本全程幂等可重跑：重复上传/导入会命中内容去重；步骤 5 的探针笔记当场删除；
步骤 6 重跑会先删旧解读 notes 再重写（引擎幂等）；步骤 7 无副作用。
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
                print("[PASS] 1/7 /health 返回 200 ok")
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
    print(f"[PASS] 2/7 上传 sample.pdf → paper_id={paper_id}")
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
                        f"[PASS] 3/7 /api/qa answer 非空（{len(answer)} 字符），"
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
            f"{HOST_DATA_DIR} 不可写（其属主与当前用户不一致；容器入口脚本本应"
            "在启动时将其 chown 为 HOST_UID）。若宿主用户 uid 非 1000，请在 .env"
            " 设置 HOST_UID=<你的 uid> 后执行"
            " `docker compose up -d --force-recreate app`。",
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
                    print(f"[PASS] 4/7 批量导入 job {job_id} done（done={done}, failed={failed}）")
                    return
                fail("step 4 批量导入", f"job {job_id} done 但结果异常：{body}")
            time.sleep(JOB_POLL_S)
        fail("step 4 批量导入", f"job {job_id} 在 {JOB_TIMEOUT_S:.0f}s 内未到 done")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


XSS_PROBE = (
    '笔记探针 <script>alert(1)</script> & "双引号" '
    "'单引号' **加粗** [链接](javascript:alert(2))"
)


def step_note_xss(client: httpx.Client, paper_id: int) -> None:
    """POST 含 <script> 的笔记 → GET 原样返回（API 层不转义不解析）→ DELETE 清理。

    渲染安全由前端 md.js 的"先整体 HTML 转义再解析"保证（Review Focus
    #5），所以 API 必须把笔记内容一字不差地存取——这里的断言就是确认
    这条契约：探针里的标签/引号/& 在 JSON 往返后完全不变。
    """
    payload = {"note_type": "annotation", "content": XSS_PROBE}
    try:
        response = client.post(
            f"/api/papers/{paper_id}/notes", json=payload, timeout=HTTP_TIMEOUT
        )
    except httpx.HTTPError as exc:
        fail("step 5 笔记 XSS 探针", f"网络错误：{exc}")
    if response.status_code != 200:
        fail("step 5 笔记 XSS 探针", f"HTTP {response.status_code}: {response.text[:300]}")
    note_id = response.json().get("note_id")
    if not isinstance(note_id, int):
        fail("step 5 笔记 XSS 探针", f"响应缺少 note_id：{response.text[:300]}")

    try:
        listing = client.get(f"/api/papers/{paper_id}/notes", timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        fail("step 5 笔记 XSS 探针", f"查询笔记失败：{exc}")
    if listing.status_code != 200:
        fail("step 5 笔记 XSS 探针", f"查询笔记失败：HTTP {listing.status_code}")
    notes = listing.json().get("notes") or []
    stored = [n for n in notes if n.get("id") == note_id]
    if not stored or stored[0].get("content") != XSS_PROBE:
        fail(
            "step 5 笔记 XSS 探针",
            f"笔记未被原样返回：期望 {XSS_PROBE!r}，实际 {stored[:1]}",
        )

    # 清理探针笔记（幂等：脚本重跑不残留）
    try:
        deleted = client.delete(f"/api/notes/{note_id}", timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        fail("step 5 笔记 XSS 探针", f"删除探针笔记失败：{exc}")
    if deleted.status_code != 200 or not deleted.json().get("deleted"):
        fail(
            "step 5 笔记 XSS 探针",
            f"删除失败：HTTP {deleted.status_code}: {deleted.text[:200]}",
        )
    print(
        f"[PASS] 5/7 笔记 XSS 探针原样存取（note_id={note_id}，内容 {len(XSS_PROBE)} 字符未转义未解析），已删除"
    )


def step_interpret(client: httpx.Client, paper_id: int) -> None:
    """POST interpret → 轮询 job 至 done（真实 LLM，40×30s 宽容）→ notes 含 six_dim。

    幂等：重跑会命中"先删后写"——引擎开始时删除该论文旧的
    section_analysis/six_dim notes 再重写。409 表示上一轮的解读任务仍在
    running，等待其结束后重新发起（重新发起的任务同样幂等）。
    """
    job_id = None
    last_error = "no attempt made"
    for attempt in range(1, READY_ATTEMPTS + 1):
        try:
            response = client.post(
                f"/api/papers/{paper_id}/interpret",
                json={},
                timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                job_id = response.json().get("job_id")
                if job_id is None:
                    fail("step 6 深度解读", f"响应缺少 job_id：{response.text[:300]}")
                break
            if response.status_code == 409:
                last_error = "已有 running 解读任务，等待其结束"
            elif response.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            else:
                fail(
                    "step 6 深度解读",
                    f"HTTP {response.status_code}: {response.text[:300]}",
                )
        print(
            f"      interpret 未启动（第 {attempt}/{READY_ATTEMPTS} 次，{last_error}），"
            f"{READY_INTERVAL_S:.0f}s 后重试…"
        )
        time.sleep(READY_INTERVAL_S)
    if job_id is None:
        fail("step 6 深度解读", f"重试 {READY_ATTEMPTS} 次后仍未启动：{last_error}")

    # 轮询：真实 LLM 逐节解读 + 六维综合是分钟级操作 → 40 次 × 30s
    for attempt in range(1, READY_ATTEMPTS + 1):
        try:
            job = client.get(f"/api/import/jobs/{job_id}", timeout=HTTP_TIMEOUT)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if job.status_code != 200:
                last_error = f"HTTP {job.status_code}: {job.text[:200]}"
            else:
                body = job.json()
                if body.get("status") == "done":
                    if body.get("failed"):
                        fail(
                            "step 6 深度解读",
                            f"job {job_id} 失败：{body.get('errors')}",
                        )
                    print(f"[PASS] 6/7 深度解读 job {job_id} done（done={body.get('done')}）")
                    break
                last_error = f"status={body.get('status')}"
        print(
            f"      interpret 进行中（第 {attempt}/{READY_ATTEMPTS} 次，{last_error}），"
            f"{READY_INTERVAL_S:.0f}s 后再查…"
        )
        time.sleep(READY_INTERVAL_S)
    else:
        fail("step 6 深度解读", f"job {job_id} 在宽容窗口内未到 done：{last_error}")

    try:
        listing = client.get(f"/api/papers/{paper_id}/notes", timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        fail("step 6 深度解读", f"查询笔记失败：{exc}")
    if listing.status_code != 200:
        fail("step 6 深度解读", f"查询笔记失败：HTTP {listing.status_code}")
    notes = listing.json().get("notes") or []
    six = [n for n in notes if n.get("note_type") == "six_dim"]
    sections = [n for n in notes if n.get("note_type") == "section_analysis"]
    if len(six) != 1 or not (six[0].get("content") or "").strip():
        fail(
            "step 6 深度解读",
            f"job done 但笔记异常：six_dim={six[:1]}，section_analysis {len(sections)} 条",
        )
    print(
        f"      GET notes：six_dim 非空（{len(six[0]['content'])} 字符），"
        f"section_analysis {len(sections)} 条"
    )


def step_compare(client: httpx.Client, paper_id: int) -> None:
    """POST /api/compare（两个已存在 id + 可选问题）→ matrix 与 citations 均非空。"""
    try:
        listing = client.get("/api/papers", timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        fail("step 7 论文对比", f"查询论文列表失败：{exc}")
    if listing.status_code != 200:
        fail("step 7 论文对比", f"查询论文列表失败：HTTP {listing.status_code}")
    papers = listing.json().get("papers") or []
    ids = [p["id"] for p in papers]
    if len(ids) < 2:
        fail(
            "step 7 论文对比",
            f"库里只有 {len(ids)} 篇论文（{ids}），对比至少需要 2 篇——请先导入另一篇再重跑",
        )
    compare_ids = [paper_id] + [i for i in ids if i != paper_id]
    compare_ids = compare_ids[:2]

    payload = {"paper_ids": compare_ids, "question": "这些方法的核心区别是什么"}
    last_error = "no attempt made"
    for attempt in range(1, READY_ATTEMPTS + 1):
        try:
            response = client.post("/api/compare", json=payload, timeout=HTTP_TIMEOUT)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                body = response.json()
                matrix = (body.get("matrix") or "").strip()
                citations = body.get("citations")
                if not matrix:
                    fail("step 7 论文对比", f"matrix 为空：{body}")
                if not citations:
                    fail("step 7 论文对比", f"citations 为空：{body}")
                print(
                    f"[PASS] 7/7 论文对比 matrix 非空（{len(matrix)} 字符），"
                    f"citations {len(citations)} 条（首页：页 {citations[0].get('page')}）"
                )
                return
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            else:
                fail(
                    "step 7 论文对比",
                    f"HTTP {response.status_code}: {response.text[:300]}",
                )
        print(
            f"      compare 未成功（第 {attempt}/{READY_ATTEMPTS} 次，{last_error}），"
            f"{READY_INTERVAL_S:.0f}s 后重试…"
        )
        time.sleep(READY_INTERVAL_S)
    fail("step 7 论文对比", f"重试 {READY_ATTEMPTS} 次后仍未成功：{last_error}")


def main() -> None:
    print(f"冒烟测试目标：{BASE_URL}")
    with httpx.Client(base_url=BASE_URL) as client:
        step_health(client)
        paper_id = step_upload(client)
        step_qa(client, paper_id)
        step_import_folder(client)
        step_note_xss(client, paper_id)
        step_interpret(client, paper_id)
        step_compare(client, paper_id)
    print("全部通过：7/7 —— 服务健康、上传、问答、批量导入、笔记安全、深度解读、论文对比均 OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
