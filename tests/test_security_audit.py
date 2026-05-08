import importlib
import json


def test_audit_records_created_for_allowed_and_blocked_calls(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
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
    assert isinstance(records[0]["trace_id"], str)
    assert records[0]["trace_id"]

    assert records[1]["tool"] == "query_entity"
    assert records[1]["decision"] == "block"
    assert records[1]["policy_version"] == "1.0.0"
    assert "forbidden" in records[1]["error"]
    assert isinstance(records[1]["trace_id"], str)
    assert records[1]["trace_id"]


def test_audit_records_include_optional_correlation_metadata(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)

    result = core_server.get_server_status(
        trace_id="trace-123",
        project_id="project-a",
        agent_id="agent-7",
        policy_id="policy-z",
        session_id="session-42",
    )

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["trace_id"] == "trace-123"
    assert record["project_id"] == "project-a"
    assert record["agent_id"] == "agent-7"
    assert record["policy_id"] == "policy-z"
    assert record["session_id"] == "session-42"


def test_search_document_by_number_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "search_document_by_number",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "document_type": "Document_РеализацияТоваровУслуг",
                    "number": kwargs["document_number"],
                    "date": "2026-05-08T09:00:00",
                    "counterparty": "ТОО Альфа Строй",
                    "amount": "100000",
                    "status": "posted",
                    "reference": "demo-ref",
                }
            ],
        },
    )

    result = core_server.search_document_by_number("000500", project_id="project-docs", agent_id="agent-docs")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "search_document_by_number"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-docs"
    assert record["agent_id"] == "agent-docs"
    assert isinstance(record["trace_id"], str)
    assert record["trace_id"]
