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


def test_get_server_status_includes_endpoint_health(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "check_endpoint_health",
        lambda **kwargs: {
            "host": "fake-host",
            "port": 80,
            "host_resolvable": True,
            "tcp_reachable": True,
            "server_alive": True,
            "odata_reachable": None,
            "metadata_readable": None,
            "details": None,
        },
    )

    result = core_server.get_server_status()

    assert result["ok"] is True
    assert result["data"]["endpoint_health"]["server_alive"] is True
    assert result["data"]["endpoint_health"]["host"] == "fake-host"


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


def test_get_customer_settlements_summary_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_customer_settlements_summary",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "counterparty": "ТОО Альфа Строй",
                    "bin_or_iin": None,
                    "debt_amount": "80000",
                    "currency": None,
                    "last_payment_date": "2026-04-24",
                    "overdue_days": 7,
                    "source_document_count": 2,
                    "source_entity": "Document_РеализацияТоваровУслуг",
                }
            ],
        },
    )

    result = core_server.get_customer_settlements_summary(date_to="2026-04-30", project_id="project-settlements")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_customer_settlements_summary"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-settlements"
    assert record["risk"] == "L0"


def test_get_cash_bank_movements_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_cash_bank_movements",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "date": "2026-04-24T10:00:00",
                    "movement_type": "incoming",
                    "account_type": "bank",
                    "counterparty": "ТОО Альфа Строй",
                    "amount": "100000",
                    "currency": "KZT",
                    "document_type": "Document_ПоступлениеНаБанковскийСчет",
                    "document_number": "000100",
                    "purpose": "Оплата по договору",
                    "source_entity": "Document_ПоступлениеНаБанковскийСчет",
                }
            ],
        },
    )

    result = core_server.get_cash_bank_movements(date_to="2026-04-30", project_id="project-movements")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_cash_bank_movements"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-movements"
    assert record["risk"] == "L0"


def test_get_supplier_settlements_summary_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_supplier_settlements_summary",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "counterparty": "ТОО Cement Trade",
                    "bin_or_iin": None,
                    "debt_amount": "110000",
                    "currency": None,
                    "last_payment_date": "2026-04-25",
                    "overdue_days": 10,
                    "source_document_count": 2,
                    "source_entity": "Document_ПоступлениеТоваровУслуг",
                }
            ],
        },
    )

    result = core_server.get_supplier_settlements_summary(date_to="2026-04-30", project_id="project-suppliers")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_supplier_settlements_summary"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-suppliers"
    assert record["risk"] == "L0"


def test_get_supplier_debt_document_breakdown_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_supplier_debt_document_breakdown",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "counterparty": "ТОО Cement Trade",
                    "debt_amount": "110000",
                    "documents": [
                        {
                            "document_date": "2026-04-20",
                            "document_number": "SUP-001",
                            "outstanding_amount": "110000",
                        }
                    ],
                }
            ],
        },
    )

    result = core_server.get_supplier_debt_document_breakdown(date_to="2026-04-30", project_id="project-supplier-docs")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_supplier_debt_document_breakdown"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-supplier-docs"
    assert record["risk"] == "L0"


def test_get_purchase_document_details_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_purchase_document_details",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "document_number": "0000000272",
                    "counterparty": "Алматинский метизный завод ТОО",
                    "line_count": 15,
                }
            ],
        },
    )

    result = core_server.get_purchase_document_details(document_number="0000000272", project_id="project-purchase-doc")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_purchase_document_details"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-purchase-doc"
    assert record["risk"] == "L0"


def test_get_purchase_receipts_summary_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_purchase_receipts_summary",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "date": "2026-05-06",
                    "supplier": "Алматинский метизный завод ТОО",
                    "item": "Шпильки резьбовые M12",
                    "quantity": 250,
                    "document_number": "0000000272",
                }
            ],
        },
    )

    result = core_server.get_purchase_receipts_summary(date_from="2026-05-01", date_to="2026-05-31", project_id="project-purchase-summary")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_purchase_receipts_summary"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-purchase-summary"
    assert record["risk"] == "L0"


def test_get_sales_document_details_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_sales_document_details",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "document_number": "0000001243",
                    "counterparty": "Розничная выручка",
                    "lines": [{"name": "GRINDA GH-540", "quantity": 1}],
                }
            ],
        },
    )

    result = core_server.get_sales_document_details(document_number="0000001243", project_id="project-sales-doc")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_sales_document_details"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-sales-doc"
    assert record["risk"] == "L0"


def test_get_sales_journal_view_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_sales_journal_view",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "date": "2026-05-05T13:25:31",
                    "document_number": "0000001248",
                    "counterparty": "ИП DWS TOO",
                    "amount": "19760",
                }
            ],
        },
    )

    result = core_server.get_sales_journal_view(date_from="2026-05-01", date_to="2026-05-31", project_id="project-sales-journal")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_sales_journal_view"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-sales-journal"
    assert record["risk"] == "L0"


def test_get_sales_receipts_summary_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_sales_receipts_summary",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "date": "2026-05-05",
                    "counterparty": "ИП DWS TOO",
                    "item": "Круглая труба",
                    "quantity": 48,
                    "document_number": "0000001241",
                }
            ],
        },
    )

    result = core_server.get_sales_receipts_summary(date_from="2026-05-01", date_to="2026-05-31", project_id="project-sales-summary")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_sales_receipts_summary"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-sales-summary"
    assert record["risk"] == "L0"


def test_get_customer_invoice_details_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_customer_invoice_details",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [{"document_number": "000127", "counterparty": "МПРО"}],
        },
    )

    result = core_server.get_customer_invoice_details(document_number="000127", project_id="project-customer-invoice-detail")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_customer_invoice_details"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-customer-invoice-detail"
    assert record["risk"] == "L0"


def test_get_customer_invoice_journal_view_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_customer_invoice_journal_view",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [{"document_number": "000127", "counterparty": "МПРО"}],
        },
    )

    result = core_server.get_customer_invoice_journal_view(date_from="2026-04-01", date_to="2026-04-30", project_id="project-customer-invoice-journal")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_customer_invoice_journal_view"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-customer-invoice-journal"
    assert record["risk"] == "L0"


def test_get_sales_management_summary_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_sales_management_summary",
        lambda **kwargs: {
            "summary": {"total_sales_amount": "490000", "total_documents": 3},
            "top_items": [{"item": "Цемент М400", "quantity": "13"}],
            "top_customers": [{"counterparty": "ТОО Альфа Строй", "sales_amount": "400000"}],
        },
    )

    result = core_server.get_sales_management_summary(date_from="2026-04-20", date_to="2026-04-30", project_id="project-sales-mgmt")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_sales_management_summary"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-sales-mgmt"
    assert record["risk"] == "L1"


def test_get_supplier_reconciliation_documents_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_supplier_reconciliation_documents",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "counterparty": "ТОО Cement Trade",
                    "reconciliation_number": "SV-001",
                    "reconciliation_date": "2026-04-30T12:00:00",
                    "purchase_document_count": 2,
                    "outgoing_payment_count": 1,
                    "source_entity": "Document_АктСверкиВзаиморасчетов",
                }
            ],
        },
    )

    result = core_server.get_supplier_reconciliation_documents(date_to="2026-04-30", project_id="project-reconciliation")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_supplier_reconciliation_documents"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-reconciliation"
    assert record["risk"] == "L0"


def test_get_procurement_recommendations_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_procurement_recommendations",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "item": "Цемент М400",
                    "recommended_purchase_qty": "10",
                }
            ],
        },
    )

    result = core_server.get_procurement_recommendations(days=30, project_id="project-procurement")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_procurement_recommendations"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-procurement"
    assert record["risk"] == "L1"


def test_get_procurement_recommendations_fast_allowed_call_is_audited(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(audit_path))

    import ashybulakstroy_mcp_1c_bridge.core_server as core_server

    core_server = importlib.reload(core_server)
    monkeypatch.setattr(
        core_server.odata,
        "get_procurement_recommendations_fast",
        lambda **kwargs: {
            "count_returned": 1,
            "data": [
                {
                    "item": "Цемент М400",
                    "recommended_purchase_qty": "10",
                }
            ],
        },
    )

    result = core_server.get_procurement_recommendations_fast(days=5, project_id="project-procurement-fast")

    assert result["ok"] is True

    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool"] == "get_procurement_recommendations_fast"
    assert record["decision"] == "allow"
    assert record["project_id"] == "project-procurement-fast"
    assert record["risk"] == "L1"
