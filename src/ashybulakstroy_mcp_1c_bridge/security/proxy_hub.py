from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .context import ensure_request_context, set_request_context
from .models import OutputPolicy, RequestContext
from .output_filter import OutputFilter
from .policy_loader import load_policy


class ProxyPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProxyRequest:
    project_id: str
    agent_id: str
    policy_id: str
    trace_id: str
    risk_level: str
    provider: str
    max_tokens: int
    cloud_provider: bool
    prompt: str


class LLMProxyHub:
    def __init__(self, policy_path: str | Path, audit_logger: AuditLogger):
        self.policy_path = Path(policy_path)
        self.audit_logger = audit_logger

    def prepare_request(
        self,
        *,
        user_query: str,
        provider: str,
        risk_level: str,
        max_tokens: int,
        project_id: str | None = None,
        agent_id: str | None = None,
        policy_id: str | None = None,
        trace_id: str | None = None,
        actor: str = "llm_proxy",
    ) -> ProxyRequest:
        policy = load_policy(self.policy_path)
        proxy_policy = policy.proxy
        if provider not in proxy_policy.provider_allowlist:
            raise ProxyPolicyError(f"Provider is not allowed by policy: {provider}")

        effective_project_id = project_id or proxy_policy.default_project_id
        effective_agent_id = agent_id or proxy_policy.default_agent_id
        effective_policy_id = policy_id or proxy_policy.policy_id
        limit = proxy_policy.token_limit_for_project(effective_project_id)
        if max_tokens > limit:
            raise ProxyPolicyError(
                f"Requested max_tokens={max_tokens} exceeds project token limit {limit} for project {effective_project_id}"
            )

        is_cloud_provider = provider in proxy_policy.cloud_providers
        prompt = user_query
        if is_cloud_provider and proxy_policy.mask_pii_before_cloud:
            prompt = self._mask_pii(prompt)

        ctx = ensure_request_context(
            trace_id=trace_id,
            actor=actor,
            project_id=effective_project_id,
            agent_id=effective_agent_id,
            policy_id=effective_policy_id,
            risk_level=risk_level,
            provider=provider,
            token_limit=limit,
            requested_tokens=max_tokens,
            user_query=user_query,
        )
        set_request_context(ctx)

        request = ProxyRequest(
            project_id=effective_project_id,
            agent_id=effective_agent_id,
            policy_id=effective_policy_id,
            trace_id=ctx.trace_id,
            risk_level=risk_level,
            provider=provider,
            max_tokens=max_tokens,
            cloud_provider=is_cloud_provider,
            prompt=prompt,
        )
        self.audit_logger.append(
            {
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "stage": "llm_proxy_request",
                "actor": actor,
                "project_id": effective_project_id,
                "agent_id": effective_agent_id,
                "policy_id": effective_policy_id,
                "trace_id": ctx.trace_id,
                "risk": risk_level,
                "provider": provider,
                "token_limit": limit,
                "requested_tokens": max_tokens,
                "cloud_provider": is_cloud_provider,
                "error": None,
            }
        )
        return request

    def record_final_answer(self, answer: str, *, actor: str = "llm_proxy", error: str | None = None) -> dict[str, Any]:
        ctx = ensure_request_context(actor=actor)
        record = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "stage": "final_answer",
            "actor": actor,
            "project_id": ctx.project_id,
            "agent_id": ctx.agent_id,
            "policy_id": ctx.policy_id,
            "trace_id": ctx.trace_id,
            "risk": ctx.risk_level,
            "provider": ctx.provider,
            "answer_chars": len(answer),
            "error": error,
        }
        self.audit_logger.append(record)
        return record

    @staticmethod
    def _mask_pii(text: str) -> str:
        filter_ = OutputFilter(
            OutputPolicy(
                max_rows=100,
                mask_iin_bin=True,
                mask_bank_accounts=True,
                block_external_urls=False,
                redact_credentials=False,
            )
        )
        return filter_.apply(text)
