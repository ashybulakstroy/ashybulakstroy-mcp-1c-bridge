from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    odata_url: str
    username: str | None
    password: str | None
    timeout_seconds: float
    verify_ssl: bool
    db_path: Path
    max_top: int


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    load_dotenv()
    odata_url = os.getenv("ONEC_ODATA_URL", "").rstrip("/")
    if not odata_url:
        # Do not raise at import time; tool calls will return a clear error.
        odata_url = ""

    return Settings(
        odata_url=odata_url,
        username=os.getenv("ONEC_USERNAME") or None,
        password=os.getenv("ONEC_PASSWORD") or None,
        timeout_seconds=float(os.getenv("ONEC_TIMEOUT_SECONDS", "60")),
        verify_ssl=_bool(os.getenv("ONEC_VERIFY_SSL"), True),
        db_path=Path(os.getenv("BRIDGE_DB_PATH", "./bridge_knowledge.sqlite3")),
        max_top=max(1, int(os.getenv("BRIDGE_MAX_TOP", "500"))),
    )
