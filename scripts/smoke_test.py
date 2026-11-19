#!/usr/bin/env python3
"""端到端冒烟：对运行中的服务验证管理链路（零模型调用）。

运行（服务已 `docker compose up -d` 且 Runner 在线）::

    .venv/bin/python scripts/smoke_test.py

步骤（任一步失败 → 打印步骤名并以退出码 1 结束）：
  1. GET  /health                      → 200 且 status == "ok"
  2. GET  /api/library/papers          → 200 且含 papers 列表
  3. GET  /api/sessions/templates      → 200 且含内置 read/compare 模板
  4. PUT/GET /api/workbench/states/{探针} → 写入后读回一致，再恢复原值
  5. GET  /api/agent/status            → Runner 在线且协议兼容

智能体执行链路（真实模型）不在冒烟内，避免重复计费；用最小材料单独验证。
脚本幂等可重跑：工作区探针先读原值、结束后恢复。
"""

from __future__ import annotations

import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:8600"
PROBE_ID = "deadbeefdeadbeefdeadbeefdeadbeef"  # 32 位 hex 探针工作区


def fail(step: str, detail: str) -> None:
    print(f"FAIL [{step}] {detail}")
    sys.exit(1)


def check_workspace(client: httpx.Client) -> None:
    """步骤 4：探针工作区写入/读回/恢复（幂等）。"""
    original = client.get(f"/api/workbench/states/{PROBE_ID}").json()
    probe = {"layout": {"left_width": 235, "right_width": 340, "left_hidden": False, "right_hidden": False},
             "tabs": [], "active_paper_id": None, "view": "read"}
    try:
        r = client.put(f"/api/workbench/states/{PROBE_ID}", json=probe)
        if r.status_code != 200:
            fail("workspace", f"PUT {r.status_code} {r.text[:200]}")
        back = client.get(f"/api/workbench/states/{PROBE_ID}").json()
        if back != probe:
            fail("workspace", "读回与写入不一致")
    finally:
        # 即使比对失败也恢复原值；首次运行会留下一条默认状态探针行（无害）。
        client.put(f"/api/workbench/states/{PROBE_ID}", json=original)


def wait_health(client: httpx.Client) -> None:
    for attempt in range(3):
        try:
            r = client.get("/health", timeout=5)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return
        except httpx.HTTPError:
            pass
        time.sleep(5)
    fail("health", "服务未就绪（/health 非 ok）")


def check_agent(client: httpx.Client) -> dict:
    """An old but healthy Runner must not pass a release check."""
    r = client.get('/api/agent/status')
    data = r.json() if r.status_code == 200 else {}
    runner = data.get('runner', {})
    if runner.get('status') != 'ok':
        fail('agent', f'Runner 不在线: {runner}')
    if data.get('runner_protocol_compatible') is not True:
        fail('agent', f"Runner 协议不匹配：需要 {data.get('required_runner_protocol')}，实际 {runner.get('protocol_version')}；请同步发布并重启宿主 Runner")
    return runner


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        wait_health(client)
        print("ok [1/5] health")

        r = client.get("/api/library/papers")
        if r.status_code != 200 or "papers" not in r.json():
            fail("library", f"{r.status_code} {r.text[:200]}")
        print(f"ok [2/5] library（{r.json().get('total', 0)} 篇论文）")

        r = client.get("/api/sessions/templates")
        ids = {t["id"] for t in r.json().get("templates", [])} if r.status_code == 200 else set()
        if not {"read", "compare"} <= ids:
            fail("templates", f"缺少内置模板: {ids}")
        print("ok [3/5] templates")

        check_workspace(client)
        print("ok [4/5] workspace")

        runner = check_agent(client)
        print(f"ok [5/5] agent（model={runner.get('model')} concurrency={runner.get('concurrency')} protocol={runner.get('protocol_version')}）")

    print("SMOKE PASS")


if __name__ == "__main__":
    main()
