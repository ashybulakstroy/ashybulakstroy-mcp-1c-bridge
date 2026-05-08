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
class ProxyPolicy:
    policy_id: str = "secure-readonly-v1"
    default_project_id: str = "default-project"
    default_agent_id: str = "mcp-1c-bridge"
    provider_allowlist: tuple[str, ...] = ()
    cloud_providers: tuple[str, ...] = ()
    project_token_limits: dict[str, int] = field(default_factory=dict)
    mask_pii_before_cloud: bool = True

    def token_limit_for_project(self, project_id: str) -> int:
        if project_id in self.project_token_limits:
            return self.project_token_limits[project_id]
        return self.project_token_limits.get("default", 4000)


@dataclass(frozen=True)
class Policy:
    version: str = "1.0.0"
    mode: str = "read_only"
    tools: dict[str, ToolPolicy] = field(default_factory=dict)
    forbidden: frozenset[str] = field(default_factory=frozenset)
    output: OutputPolicy = field(default_factory=OutputPolicy)
    proxy: ProxyPolicy = field(default_factory=ProxyPolicy)


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


@dataclass(frozen=True)
class RequestContext:
    trace_id: str
    actor: str = "mcp_client"
    project_id: str | None = None
    agent_id: str | None = None
    policy_id: str | None = None
    session_id: str | None = None
    risk_level: str | None = None
    tool_name: str | None = None
    provider: str | None = None
    token_limit: int | None = None
    requested_tokens: int | None = None
    user_query: str | None = None
