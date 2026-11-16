FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# Dependency layer: copied (and installed) before the source so that code
# changes do not bust the pip cache.
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir \
      -i https://pypi.tuna.tsinghua.edu.cn/simple \
      -r requirements.txt

COPY app ./app

# TODO(embedding task): pre-download the bge-m3 model at build time, e.g.
#   RUN pip install --no-cache-dir sentence-transformers \
#       && python -c "from sentence_transformers import SentenceTransformer; \
#                      SentenceTransformer('BAAI/bge-m3')"
# NOTE(torch): the CPU build is required (no GPU) — install it from the PyTorch
#   CPU index BEFORE sentence-transformers so pip does not drag in the
#   multi-GB CUDA wheels from PyPI:
#   RUN pip install --no-cache-dir torch \
#         --index-url https://download.pytorch.org/whl/cpu \
#       && pip install --no-cache-dir sentence-transformers qdrant-client
# (Deliberately not done in the P1 skeleton task to keep the image slim.)

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
