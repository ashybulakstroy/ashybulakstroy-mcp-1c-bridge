import importlib
import json

import httpx
import pytest

from ashybulakstroy_mcp_1c_bridge.security import AuditLogger, LLMProxyHub, ProxyPolicyError, clear_request_context


def test_proxy_hub_masks_pii_for_cloud_provider_and_writes_audit(tmp_path):
    clear_request_context()
    policy_path = tmp_path / "policy.yaml"
    audit_path = tmp_path / "audit.jsonl"
    policy_path.write_text(
        """
version: "1.0.0"
mode: read_only
proxy:
  policy_id: secure-readonly-v1
  default_project_id: demo-project
  default_agent_id: demo-agent
  provider_allowlist:
    - gpt_compatible
  cloud_providers:
    - gpt_compatible
  project_token_limits:
    default: 2000
    demo-project: 1500
  mask_pii_before_cloud: true
tools: {}
forbidden: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    hub = LLMProxyHub(policy_path, AuditLogger(audit_path))
    req = hub.prepare_request(
        user_query="ИИН 123456789012 и счет KZ 12345678901234567890",
        provider="gpt_compatible",
        risk_level="L1",
        max_tokens=1200,
    )

    assert req.project_id == "demo-project"
    assert req.agent_id == "demo-agent"
    assert req.policy_id == "secure-readonly-v1"
    assert req.trace_id
    assert "1234****9012" in req.prompt
    assert "************" in req.prompt

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["stage"] == "llm_proxy_request"
    assert records[0]["trace_id"] == req.trace_id
    assert records[0]["project_id"] == "demo-project"


def test_proxy_hub_enforces_provider_allowlist_and_token_limits(tmp_path):
    clear_request_context()
    policy_path = tmp_path / "policy.yaml"
    audit_path = tmp_path / "audit.jsonl"
    policy_path.write_text(
        """
version: "1.0.0"
mode: read_only
proxy:
  policy_id: secure-readonly-v1
  default_project_id: project-a
  default_agent_id: agent-a
  provider_allowlist:
    - local_or_low_cost
  cloud_providers: []
  project_token_limits:
    default: 1000
    project-a: 800
tools: {}
forbidden: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    hub = LLMProxyHub(policy_path, AuditLogger(audit_path))

    with pytest.raises(ProxyPolicyError):
        hub.prepare_request(
            user_query="test",
            provider="gpt_compatible",
            risk_level="L0",
            max_tokens=100,
        )

    with pytest.raises(ProxyPolicyError):
        hub.prepare_request(
            user_query="test",
            provider="local_or_low_cost",
            risk_level="L0",
            max_tokens=1200,
        )


def test_trace_id_links_llm_proxy_mcp_tool_and_1c_adapter(monkeypatch, tmp_path):
    clear_request_context()
    policy_path = tmp_path / "proxy_only_policy.yaml"
    audit_path = tmp_path / "audit.jsonl"
    policy_path.write_text(
        """
version: "1.0.0"
mode: read_only
proxy:
  policy_id: secure-readonly-v1
  default_project_id: trace-project
  default_agent_id: trace-agent
  provider_allowlist:
    - gpt_compatible
  cloud_providers:
    - gpt_compatible
  project_token_limits:
    default: 2000
forbidden: []
tools:
  list_entities:
    risk: L0
    capabilities:
      - read_metadata
    auto_approval: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("ONEC_ODATA_URL", "http://example.test/odata")

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    hub = LLMProxyHub(policy_path, AuditLogger(audit_path))
    req = hub.prepare_request(
        user_query="Покажи список сущностей",
        provider="gpt_compatible",
        risk_level="L0",
        max_tokens=500,
    )

    xml = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="Demo">
      <EntityType Name="Catalog_Контрагенты">
        <Property Name="Description" Type="Edm.String" Nullable="true" />
      </EntityType>
      <EntityContainer Name="DefaultContainer">
        <EntitySet Name="Catalog_Контрагенты" EntityType="Demo.Catalog_Контрагенты" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    response = httpx.Response(
        200,
        text=xml,
        request=httpx.Request("GET", "http://example.test/odata/$metadata"),
    )
    monkeypatch.setattr(core_server.odata.client, "get", lambda *args, **kwargs: response)

    result = core_server.list_entities()

    assert result["ok"] is True
    hub.record_final_answer("Готово")

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    stages = {record["stage"] for record in records}
    assert {"llm_proxy_request", "1c_adapter_call", "mcp_tool_call", "final_answer"} <= stages

    linked = [record for record in records if record["trace_id"] == req.trace_id]
    assert len(linked) == 4
    assert {record["stage"] for record in linked} == {"llm_proxy_request", "1c_adapter_call", "mcp_tool_call", "final_answer"}
    clear_request_context()
