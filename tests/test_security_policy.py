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
