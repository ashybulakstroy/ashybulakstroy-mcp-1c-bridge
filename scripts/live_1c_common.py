from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Live1CConfig:
    base_url: str
    service_url: str
    username: str | None
    password: str | None
    timeout_seconds: float
    verify_ssl: bool


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def prepare_live_env() -> Live1CConfig:
    load_dotenv()
    base_url = (os.getenv("ONEC_ODATA_BASE_URL") or "").rstrip("/")
    service_url = (os.getenv("ONEC_ODATA_URL") or "").rstrip("/")
    username = os.getenv("ONEC_USERNAME") or os.getenv("ONEC_ODATA_USERNAME") or None
    password = os.getenv("ONEC_PASSWORD") or os.getenv("ONEC_ODATA_PASSWORD") or None

    if base_url:
        service_url = f"{base_url}/odata/standard.odata"
    elif not service_url and base_url:
        service_url = f"{base_url}/odata/standard.odata"
    if not base_url and service_url.lower().endswith("/odata/standard.odata"):
        base_url = service_url[: -len("/odata/standard.odata")]

    if service_url and not os.getenv("ONEC_ODATA_URL"):
        os.environ["ONEC_ODATA_URL"] = service_url
    if username and not os.getenv("ONEC_USERNAME"):
        os.environ["ONEC_USERNAME"] = username
    if password and not os.getenv("ONEC_PASSWORD"):
        os.environ["ONEC_PASSWORD"] = password

    return Live1CConfig(
        base_url=base_url,
        service_url=service_url,
        username=username,
        password=password,
        timeout_seconds=float(os.getenv("ONEC_TIMEOUT_SECONDS", "60")),
        verify_ssl=_bool(os.getenv("ONEC_VERIFY_SSL"), True),
    )


def configure_quiet_logging() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def redact_text(text: str, secrets: list[str | None]) -> str:
    masked = text
    for secret in secrets:
        if secret:
            masked = masked.replace(secret, "***")
    return masked


def sanitize_error(exc: Exception, config: Live1CConfig) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    return redact_text(text, [config.username, config.password])


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, content: str) -> None:
    ensure_parent(path).write_text(content, encoding="utf-8")


def summarize_rows(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("rows", "data", "results", "entities", "items", "inventory_candidates", "payment_candidates", "sales_candidates"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def contains_internal_url(payload: Any, service_url: str, base_url: str) -> bool:
    text = json.dumps(payload, ensure_ascii=False)
    return service_url in text or base_url in text
