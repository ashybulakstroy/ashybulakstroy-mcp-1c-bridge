from pathlib import Path

from ashybulakstroy_mcp_1c_bridge.security import DecisionAction, DecisionEngine, RiskLevel, load_policy


def test_load_policy_defaults_to_read_only_and_parses_capabilities():
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_test.yaml")

    assert policy.mode == "read_only"
    assert policy.version == "1.0.0"
    assert policy.tools["allowed_tool"].risk is RiskLevel.L0
    assert policy.tools["allowed_tool"].capabilities[0].name == "read_metadata"


def test_decision_engine_allows_l0_tool_from_allowlist():
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_test.yaml")
    engine = DecisionEngine(policy)

    decision = engine.decide("allowed_tool")

    assert decision.action is DecisionAction.ALLOW
    assert decision.allowed is True
    assert decision.risk is RiskLevel.L0


def test_decision_engine_denies_unknown_tool():
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_test.yaml")
    engine = DecisionEngine(policy)

    decision = engine.decide("unknown_tool")

    assert decision.action is DecisionAction.DENY
    assert decision.allowed is False
    assert "allowlist" in decision.reason


def test_decision_engine_blocks_forbidden_tool():
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_test.yaml")
    engine = DecisionEngine(policy)

    decision = engine.decide("forbidden_tool")

    assert decision.action is DecisionAction.BLOCK
    assert "forbidden" in decision.reason


def test_decision_engine_denies_l2_in_read_only_mode():
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_test.yaml")
    engine = DecisionEngine(policy)

    decision = engine.decide("write_tool")

    assert decision.action is DecisionAction.DENY
    assert decision.risk is RiskLevel.L2
    assert "read_only" in decision.reason


def test_decision_engine_blocks_l3_and_l4():
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_test.yaml")
    engine = DecisionEngine(policy)

    l3 = engine.decide("sensitive_tool")
    l4 = engine.decide("destructive_tool")

    assert l3.action is DecisionAction.BLOCK
    assert l3.risk is RiskLevel.L3
    assert l4.action is DecisionAction.BLOCK
    assert l4.risk is RiskLevel.L4


def test_main_policy_covers_customer_settlements_summary():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_customer_settlements_summary"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_customer_settlements"]


def test_demo_docs_mark_customer_settlements_as_management_estimate():
    demo_readme = Path("docs/DEMO_READONLY_SECURE_MODE.md").read_text(encoding="utf-8")
    demo_prompts = Path("docs/DEMO_PROMPTS.md").read_text(encoding="utf-8")

    assert "не официальный бухгалтерский акт сверки" in demo_readme
    assert "не официальный бухгалтерский акт сверки" in demo_prompts
    assert "официальный бухгалтерский баланс взаиморасчетов" not in demo_readme


def test_main_policy_covers_cash_bank_movements():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_cash_bank_movements"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_cash_bank_movements"]


def test_main_policy_covers_supplier_settlements_summary():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_supplier_settlements_summary"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_supplier_settlements"]


def test_main_policy_covers_supplier_debt_document_breakdown():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_supplier_debt_document_breakdown"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_supplier_settlements", "read_documents"]


def test_main_policy_covers_purchase_document_details():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_purchase_document_details"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_purchase_receipts_summary():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_purchase_receipts_summary"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_sales_document_details():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_sales_document_details"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_sales_journal_view():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_sales_journal_view"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_sales_receipts_summary():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_sales_receipts_summary"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_customer_invoice_details():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_customer_invoice_details"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_customer_invoice_journal_view():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_customer_invoice_journal_view"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_documents"]


def test_main_policy_covers_sales_management_summary():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_sales_management_summary"]

    assert tool.risk is RiskLevel.L1
    assert [cap.name for cap in tool.capabilities] == ["read_documents", "create_local_report"]


def test_main_policy_covers_supplier_reconciliation_documents():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_supplier_reconciliation_documents"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_supplier_reconciliation", "read_documents"]


def test_main_policy_covers_procurement_recommendations():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_procurement_recommendations"]

    assert tool.risk is RiskLevel.L1
    assert [cap.name for cap in tool.capabilities] == ["read_inventory", "read_documents", "create_local_report"]


def test_main_policy_covers_procurement_recommendations_fast():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_procurement_recommendations_fast"]

    assert tool.risk is RiskLevel.L1
    assert [cap.name for cap in tool.capabilities] == ["read_inventory", "read_documents", "create_local_report"]


def test_main_policy_covers_material_statement_view():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_material_statement_view"]

    assert tool.risk is RiskLevel.L1
    assert [cap.name for cap in tool.capabilities] == ["read_inventory", "create_local_report"]


def test_main_policy_covers_sales_item_picker_view():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_sales_item_picker_view"]

    assert tool.risk is RiskLevel.L0
    assert [cap.name for cap in tool.capabilities] == ["read_inventory"]


def test_main_policy_covers_top_selling_items_with_stock():
    policy = load_policy(Path("config") / "policy.yaml")

    tool = policy.tools["get_top_selling_items_with_stock"]

    assert tool.risk is RiskLevel.L1
    assert [cap.name for cap in tool.capabilities] == ["read_documents", "read_inventory", "create_local_report"]


def test_demo_docs_mark_cash_bank_movements_as_operational_view():
    demo_readme = Path("docs/DEMO_READONLY_SECURE_MODE.md").read_text(encoding="utf-8")
    demo_prompts = Path("docs/DEMO_PROMPTS.md").read_text(encoding="utf-8")

    assert "read-only operational view" in demo_readme
    assert "не официальная банковская выписка" in demo_readme
    assert "не официальная банковская выписка" in demo_prompts
