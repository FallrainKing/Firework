"""Application configuration loaded from environment variables (12-factor)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Runtime settings; all values come from the environment / .env file."""

    data_dir: Path
    qdrant_url: str
    llm_providers: list[dict] = field(default_factory=list)
    llm_fast: str = ""
    llm_strong: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        providers_raw = os.getenv("LLM_PROVIDERS", "").strip()
        try:
            providers = json.loads(providers_raw) if providers_raw else []
        except json.JSONDecodeError as exc:
            # fail fast: a typo'd LLM_PROVIDERS silently degrading to "no
            # providers" turns every chat into an opaque gateway failure
            raise ValueError(
                f"LLM_PROVIDERS is not valid JSON ({exc}); refusing to start"
                " with an empty provider list"
            ) from exc
        if not isinstance(providers, list):
            raise ValueError(
                "LLM_PROVIDERS must be a JSON array of provider objects,"
                f" got {type(providers).__name__}"
            )
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            llm_providers=providers,
            llm_fast=os.getenv("LLM_FAST", ""),
            llm_strong=os.getenv("LLM_STRONG", ""),
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"
