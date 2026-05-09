from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .audit import AuditLogger
from .context import ensure_request_context, request_context
from .decision_engine import DecisionEngine
from .models import Policy, PolicyDecision
from .output_filter import OutputFilter
from .policy_loader import load_policy

CORRELATION_FIELDS = ("trace_id", "project_id", "agent_id", "policy_id", "session_id")


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
        metadata = self._extract_correlation_metadata(kwargs)
        ctx = ensure_request_context(
            actor=actor,
            trace_id=metadata.get("trace_id"),
            project_id=metadata.get("project_id") or policy.proxy.default_project_id,
            agent_id=metadata.get("agent_id") or policy.proxy.default_agent_id,
            policy_id=metadata.get("policy_id") or policy.proxy.policy_id,
            session_id=metadata.get("session_id"),
            tool_name=tool_name,
            risk_level=decision.risk.value if decision.risk else None,
            capabilities=tuple(cap.name for cap in decision.capabilities),
            decision=decision.action.value,
            policy_version=policy.version,
        )
        if not decision.allowed:
            duration_ms = int((perf_counter() - started) * 1000)
            error = decision.reason
            self._audit(actor=actor, decision=decision, duration_ms=duration_ms, error=error, policy=policy, ctx=ctx)
            return {
                "ok": False,
                "error": error,
                "type": "PolicyBlocked" if decision.action.value == "block" else "PolicyDenied",
            }

        error: str | None = None
        try:
            with request_context(ctx):
                result = func(*args, **kwargs)
        except Exception as exc:
            error = str(exc)
            duration_ms = int((perf_counter() - started) * 1000)
            self._audit(actor=actor, decision=decision, duration_ms=duration_ms, error=error, policy=policy, ctx=ctx)
            raise

        if isinstance(result, dict) and result.get("ok") is False:
            error = str(result.get("error") or "")
        else:
            result = output_filter.apply(result)
        duration_ms = int((perf_counter() - started) * 1000)
        self._audit(actor=actor, decision=decision, duration_ms=duration_ms, error=error, policy=policy, ctx=ctx)
        return result

    def _load_policy(self) -> Policy:
        return load_policy(self.policy_path)

    @staticmethod
    def _extract_correlation_metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
        return {field: kwargs.pop(field, None) for field in CORRELATION_FIELDS}

    def _audit(self, actor: str, decision: PolicyDecision, duration_ms: int, error: str | None, policy: Policy, ctx) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "stage": "mcp_tool_call",
            "actor": actor,
            "project_id": ctx.project_id,
            "agent_id": ctx.agent_id,
            "policy_id": ctx.policy_id,
            "session_id": ctx.session_id,
            "trace_id": ctx.trace_id,
            "tool": decision.tool,
            "risk": decision.risk.value if decision.risk else None,
            "capabilities": [cap.name for cap in decision.capabilities],
            "decision": decision.action.value,
            "policy_version": policy.version,
            "duration_ms": duration_ms,
            "provider": ctx.provider,
            "requested_tokens": ctx.requested_tokens,
            "error": error,
        }
        self.audit_logger.append(record)
