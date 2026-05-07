from __future__ import annotations

from .models import DecisionAction, Policy, PolicyDecision, RiskLevel


class DecisionEngine:
    def __init__(self, policy: Policy):
        self.policy = policy

    def decide(self, tool_name: str) -> PolicyDecision:
        if tool_name in self.policy.forbidden:
            return PolicyDecision(
                action=DecisionAction.BLOCK,
                tool=tool_name,
                reason="tool is forbidden by policy denylist",
            )

        tool_policy = self.policy.tools.get(tool_name)
        if tool_policy is None:
            return PolicyDecision(
                action=DecisionAction.DENY,
                tool=tool_name,
                reason="tool is not present in policy allowlist",
            )

        if not tool_policy.capabilities:
            return PolicyDecision(
                action=DecisionAction.DENY,
                tool=tool_name,
                reason="tool has no declared capabilities in policy",
                risk=tool_policy.risk,
                capabilities=tool_policy.capabilities,
            )

        if tool_policy.risk in {RiskLevel.L3, RiskLevel.L4}:
            return PolicyDecision(
                action=DecisionAction.BLOCK,
                tool=tool_name,
                reason=f"risk level {tool_policy.risk.value} is always blocked",
                risk=tool_policy.risk,
                capabilities=tool_policy.capabilities,
            )

        if self.policy.mode == "read_only" and tool_policy.risk == RiskLevel.L2:
            return PolicyDecision(
                action=DecisionAction.DENY,
                tool=tool_name,
                reason="risk level L2 is denied in read_only mode",
                risk=tool_policy.risk,
                capabilities=tool_policy.capabilities,
            )

        return PolicyDecision(
            action=DecisionAction.ALLOW,
            tool=tool_name,
            reason="tool is allowed by policy",
            risk=tool_policy.risk,
            capabilities=tool_policy.capabilities,
        )
