# Stage 1: build the Vue workbench (frontend/ → dist).
FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the Python app.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# Dependency layer: copied (and installed) before the source so that code
# changes do not bust the pip cache.
COPY requirements.txt pyproject.toml ./

# torch MUST be the CPU build: installed from the PyTorch CPU index FIRST
# (with the fast local mirror for its pure-python deps) so that the later
# `pip install -r requirements.txt` — which pulls in sentence-transformers,
# itself depending on torch — sees torch>=2.5 already satisfied and never
# drags in the multi-GB CUDA wheels from PyPI.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch \
 && pip install --no-cache-dir \
      -i https://pypi.tuna.tsinghua.edu.cn/simple \
      -r requirements.txt

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY app ./app
COPY skills ./skills
COPY plugins/zotero ./plugins/zotero
COPY scripts/build_zotero_plugin.py ./scripts/build_zotero_plugin.py
RUN python scripts/build_zotero_plugin.py
COPY plugins/agent-skill ./plugins/agent-skill
COPY scripts/build_agent_skill.py ./scripts/build_agent_skill.py
RUN python scripts/build_agent_skill.py
# Vue 构建产物覆盖到 app/web（vendor/ 已在仓库中，dist 不含 vendor）。
COPY --from=frontend /build/dist/ ./app/web/

# The bge-m3 embedding model (~2.3GB) is deliberately NOT downloaded at build
# time (slow, and a failed retry busts the whole layer). docker-compose.yml
# mounts ./data/hf as the HF cache and the app downloads the model through
# HF_ENDPOINT=https://hf-mirror.com on first startup (one-off, 5–15 min;
# while it runs the container is not listening yet — /health retries cover it).

EXPOSE 8000

# entrypoint: self-heal the /app/data mount ownership (docker auto-creates
# ./data as root on the host, which would lock the host user out of it);
# then hand off to the CMD below. See docker-entrypoint.sh.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
