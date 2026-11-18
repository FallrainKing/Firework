#!/bin/sh
# 一键发布：备份 → 构建 → 重启 app/backup → 重启 Runner → 冒烟。
# 需要 docker 权限（默认 sudo docker；已在 docker 组可 DOCKER=docker 覆盖）。
# 从任意目录运行均可。发布前确认无在途智能体任务（重启会标记 failed）。
set -eu
cd "$(dirname "$0")/.."
DOCKER="${DOCKER:-sudo docker}"

echo "== 1/5 备份（迁移前）=="
$DOCKER exec research-assistant-backup-1 /ops/backup.sh

echo "== 2/5 构建镜像 =="
$DOCKER compose build app backup

echo "== 3/5 重启 app/backup（自动应用迁移 0008）=="
$DOCKER compose up -d app backup

echo "== 4/5 重启 Runner =="
systemctl --user restart research-agent-runner

echo "== 5/5 等待就绪 + 冒烟 =="
i=0
until curl -sf http://127.0.0.1:8600/health >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -gt 90 ]; then
    echo "app 180s 内未就绪，查看：$DOCKER compose logs app" >&2
    exit 1
  fi
  sleep 2
done
.venv/bin/python scripts/smoke_test.py
echo "deploy: done"
