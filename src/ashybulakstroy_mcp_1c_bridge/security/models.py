from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class DecisionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    BLOCK = "block"


@dataclass(frozen=True)
class Capability:
    name: str


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    risk: RiskLevel
    capabilities: tuple[Capability, ...] = ()
    auto_approval: bool = True


@dataclass(frozen=True)
class OutputPolicy:
    max_rows: int = 100
    mask_iin_bin: bool = False
    mask_bank_accounts: bool = False
    block_external_urls: bool = True
    redact_credentials: bool = True


@dataclass(frozen=True)
class Policy:
    version: str = "1.0.0"
    mode: str = "read_only"
    tools: dict[str, ToolPolicy] = field(default_factory=dict)
    forbidden: frozenset[str] = field(default_factory=frozenset)
    output: OutputPolicy = field(default_factory=OutputPolicy)


@dataclass(frozen=True)
class PolicyDecision:
    action: DecisionAction
    tool: str
    reason: str
    risk: RiskLevel | None = None
    capabilities: tuple[Capability, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.action is DecisionAction.ALLOW
