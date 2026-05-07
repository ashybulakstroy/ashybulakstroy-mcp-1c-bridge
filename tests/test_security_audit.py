import importlib
import json
from pathlib import Path


def test_audit_records_created_for_allowed_and_blocked_calls(monkeypatch, tmp_path):
    policy_path = tmp_path / "policy.yaml"
    audit_path = tmp_path / "audit.jsonl"
    policy_path.write_text(
        """
version: "1.0.0"
mode: read_only
forbidden:
  - query_entity
tools:
  get_server_status:
    risk: L0
    capabilities:
      - read_metadata
    auto_approval: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BRIDGE_POLICY_PATH", str(policy_path))
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)

    allowed = core_server.get_server_status()
    blocked = core_server.query_entity("Catalog_Контрагенты")

    assert allowed["ok"] is True
    assert blocked["ok"] is False
    assert blocked["type"] == "PolicyBlocked"

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2

    assert records[0]["tool"] == "get_server_status"
    assert records[0]["decision"] == "allow"
    assert records[0]["policy_version"] == "1.0.0"
    assert records[0]["duration_ms"] >= 0
    assert records[0]["error"] is None

    assert records[1]["tool"] == "query_entity"
    assert records[1]["decision"] == "block"
    assert records[1]["policy_version"] == "1.0.0"
    assert "forbidden" in records[1]["error"]
