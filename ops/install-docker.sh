#!/usr/bin/env bash
# Docker 安装脚本（国内源版）— Ubuntu 24.04 (noble)
# 用途：安装 Docker Engine + Compose 插件、配置镜像加速、
#       将当前用户加入 docker 组、设置合盖不休眠与服务自启。
# 用法：sudo bash install-docker.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "错误：请用 sudo 运行（sudo bash install-docker.sh）" >&2
  exit 1
fi

echo "==> 1/6 安装依赖"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg

echo "==> 2/6 添加 Docker apt 仓库（阿里云镜像源）"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu noble stable" \
  > /etc/apt/sources.list.d/docker.list

echo "==> 3/6 安装 Docker Engine + Compose 插件"
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

echo "==> 4/6 配置镜像加速"
install -m 0644 /dev/null /etc/docker/daemon.json
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.net"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF

echo "==> 5/6 将用户加入 docker 组 + 服务自启"
usermod -aG docker "${SUDO_USER:-f}"
systemctl enable --now docker containerd

echo "==> 6/6 合盖不休眠（7x24 无人值守）"
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/nosuspend.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
IdleAction=ignore
EOF
systemctl restart systemd-logind

echo
echo "================ 验证 ================"
systemctl is-active docker
docker --version
docker compose version
getent group docker | grep -o "${SUDO_USER:-f}" \
  && echo "✅ 用户已在 docker 组（重新登录后免 sudo 用 docker）" \
  || echo "⚠️ 用户未加入 docker 组"
grep HandleLidSwitch /etc/systemd/logind.conf.d/nosuspend.conf
echo "✅ 安装完成。请退出并重新登录一次，使 docker 组生效。"
