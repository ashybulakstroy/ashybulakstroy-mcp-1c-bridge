from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Capability, OutputPolicy, Policy, RiskLevel, ToolPolicy


def _capabilities(values: list[str] | None) -> tuple[Capability, ...]:
    return tuple(Capability(name=v) for v in (values or []))


def _tool_policy(name: str, raw: dict[str, Any]) -> ToolPolicy:
    return ToolPolicy(
        name=name,
        risk=RiskLevel(raw["risk"]),
        capabilities=_capabilities(raw.get("capabilities")),
        auto_approval=bool(raw.get("auto_approval", True)),
    )


def _output_policy(raw: dict[str, Any] | None) -> OutputPolicy:
    raw = raw or {}
    return OutputPolicy(
        max_rows=max(1, int(raw.get("max_rows", 100))),
        mask_iin_bin=bool(raw.get("mask_iin_bin", False)),
        mask_bank_accounts=bool(raw.get("mask_bank_accounts", False)),
        block_external_urls=bool(raw.get("block_external_urls", True)),
        redact_credentials=bool(raw.get("redact_credentials", True)),
    )


def load_policy(path: str | Path) -> Policy:
    policy_path = Path(path)
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    tools_raw = raw.get("tools") or {}
    tools = {name: _tool_policy(name, value or {}) for name, value in tools_raw.items()}
    forbidden = frozenset(str(x) for x in (raw.get("forbidden") or []))
    return Policy(
        version=str(raw.get("version", "1.0.0")),
        mode=str(raw.get("mode", "read_only")),
        tools=tools,
        forbidden=forbidden,
        output=_output_policy(raw.get("output")),
    )
