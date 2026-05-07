from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .audit import AuditLogger
from .decision_engine import DecisionEngine
from .models import Policy, PolicyDecision
from .output_filter import OutputFilter
from .policy_loader import load_policy


class SecureToolRunner:
    def __init__(self, policy_path: str | Path, audit_logger: AuditLogger):
        self.policy_path = Path(policy_path)
        self.audit_logger = audit_logger

    def run(self, tool_name: str, func: Callable[..., Any], *args: Any, actor: str = "mcp_client", **kwargs: Any) -> Any:
        started = perf_counter()
        policy = self._load_policy()
        decision_engine = DecisionEngine(policy)
        output_filter = OutputFilter(policy.output)
        decision = decision_engine.decide(tool_name)
        if not decision.allowed:
            duration_ms = int((perf_counter() - started) * 1000)
            error = decision.reason
            self._audit(actor=actor, decision=decision, duration_ms=duration_ms, error=error, policy=policy)
            return {
                "ok": False,
                "error": error,
                "type": "PolicyBlocked" if decision.action.value == "block" else "PolicyDenied",
            }

        error: str | None = None
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            error = str(exc)
            duration_ms = int((perf_counter() - started) * 1000)
            self._audit(actor=actor, decision=decision, duration_ms=duration_ms, error=error, policy=policy)
            raise

        if isinstance(result, dict) and result.get("ok") is False:
            error = str(result.get("error") or "")
        else:
            result = output_filter.apply(result)
        duration_ms = int((perf_counter() - started) * 1000)
        self._audit(actor=actor, decision=decision, duration_ms=duration_ms, error=error, policy=policy)
        return result

    def _load_policy(self) -> Policy:
        return load_policy(self.policy_path)

    def _audit(self, actor: str, decision: PolicyDecision, duration_ms: int, error: str | None, policy: Policy) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "actor": actor,
            "tool": decision.tool,
            "risk": decision.risk.value if decision.risk else None,
            "capabilities": [cap.name for cap in decision.capabilities],
            "decision": decision.action.value,
            "policy_version": policy.version,
            "duration_ms": duration_ms,
            "error": error,
        }
        self.audit_logger.append(record)
