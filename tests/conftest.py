"""Shared test configuration.

Ruling R4: HuggingFace is unreachable from this network, so all model
downloads must go through the hf-mirror.com mirror. This must be set BEFORE
anything imports ``sentence_transformers`` (the endpoint is read at import
time by the huggingface_hub machinery), hence it lives at the very top of
conftest.py, before any test module can run.
"""

import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
