import importlib
from pathlib import Path

import pytest
import yaml


def _default_policy() -> dict:
    return yaml.safe_load(Path("config/policy.yaml").read_text(encoding="utf-8"))


def test_every_registered_mcp_tool_has_policy_coverage():
    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    errors = core_server.validate_secure_tool_policy_coverage(core_server.POLICY, core_server.mcp)

    assert errors == []
    assert set(core_server.get_registered_mcp_tool_names(core_server.mcp)) == core_server.SECURE_REGISTERED_TOOL_NAMES


def test_startup_validation_fails_when_registered_tool_missing_policy(monkeypatch, tmp_path):
    policy = _default_policy()
    policy["tools"].pop("get_server_status", None)
    policy_path = tmp_path / "missing_tool_policy.yaml"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False, allow_unicode=True), encoding="utf-8")

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    monkeypatch.setenv("BRIDGE_POLICY_PATH", str(policy_path))
    with pytest.raises(RuntimeError, match="missing from policy allowlist"):
        importlib.reload(core_server)
    monkeypatch.delenv("BRIDGE_POLICY_PATH", raising=False)
    importlib.reload(core_server)


def test_startup_validation_fails_when_forbidden_tool_is_allowed(monkeypatch, tmp_path):
    policy = _default_policy()
    policy.setdefault("tools", {})["query_entity"] = {
        "risk": "L0",
        "capabilities": ["read_documents"],
        "auto_approval": True,
    }
    policy_path = tmp_path / "forbidden_allowed_policy.yaml"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False, allow_unicode=True), encoding="utf-8")

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    monkeypatch.setenv("BRIDGE_POLICY_PATH", str(policy_path))
    with pytest.raises(RuntimeError, match="both forbidden and allowed"):
        importlib.reload(core_server)
    monkeypatch.delenv("BRIDGE_POLICY_PATH", raising=False)
    importlib.reload(core_server)
