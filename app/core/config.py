"""Application configuration loaded from environment variables (12-factor).

Model credentials are NOT configured here: all LLM work goes through the host
Claude Runner, which reads the host's existing Claude configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    """Runtime settings; all values come from the environment / .env file."""

    data_dir: Path
    qdrant_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"
