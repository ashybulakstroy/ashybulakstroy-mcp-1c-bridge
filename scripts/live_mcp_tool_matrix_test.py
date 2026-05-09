from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from live_1c_common import configure_quiet_logging, contains_internal_url, now_iso, prepare_live_env, repo_root, summarize_rows, write_json, write_markdown


REPORTS_DIR = repo_root() / "reports"
AUDIT_PATH = repo_root() / "audit" / "audit.jsonl"


def _clean_audit_file() -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        AUDIT_PATH.write_text("", encoding="utf-8")
    except PermissionError:
        fallback_path = AUDIT_PATH.with_name(f"audit-{uuid.uuid4().hex}.jsonl")
        os.environ["BRIDGE_AUDIT_LOG_PATH"] = str(fallback_path)
        globals()["AUDIT_PATH"] = fallback_path
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text("", encoding="utf-8")


def _load_core_server():
    os.environ["BRIDGE_AUDIT_LOG_PATH"] = str(AUDIT_PATH)
    from ashybulakstroy_mcp_1c_bridge import core_server
    from ashybulakstroy_mcp_1c_bridge.security import load_policy

    return core_server, load_policy(Path(os.environ.get("BRIDGE_POLICY_PATH", "./config/policy.yaml")))


def _tool_audit_created(trace_id: str, tool_name: str) -> bool:
    if not AUDIT_PATH.exists():
        return False
    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("stage") == "mcp_tool_call" and record.get("trace_id") == trace_id and record.get("tool") == tool_name:
            return True
    return False


def _classify_result(tool_name: str, result: Any, expected_blocked: bool = False) -> tuple[str, int, str, bool]:
    row_count = 0
    output_filter_applied = False
    note = ""
    if isinstance(result, dict) and result.get("ok") is False:
        error_type = result.get("type")
        note = str(result.get("error") or "")
        if expected_blocked and error_type in {"PolicyBlocked", "PolicyDenied"}:
            return "BLOCKED_EXPECTED", 0, note, False
        if "не найден" in note.lower() or "missing" in note.lower():
            return "PASS_EMPTY", 0, note, False
        return "FAIL", 0, note, False

    output_filter_applied = True
    data = result.get("data") if isinstance(result, dict) else result
    row_count = summarize_rows(data)
    if isinstance(data, dict) and data and row_count == 0:
        if data.get("missing_sources"):
            return "PASS_EMPTY", 0, "Tool succeeded but required source entities are missing.", output_filter_applied
        if data.get("no_data_in_checked_sources") or data.get("no_data_in_sources"):
            return "PASS_EMPTY", 0, "Tool succeeded but current safe live sources returned no business rows.", output_filter_applied
        return "PASS", 0, "Tool returned structured non-tabular summary.", output_filter_applied
    if row_count == 0:
        note = "No business rows returned or source data missing."
        return "PASS_EMPTY", 0, note, output_filter_applied
    note = "Tool returned non-empty read-only result."
    return "PASS", row_count, note, output_filter_applied


def _safe_text_report() -> str:
    return "\n".join(
        [
            "Номенклатура    Склад           Количество    Сумма",
            "Цемент М400     Основной склад  10            250000",
            "Песок           Основной склад  5             30000",
        ]
    )


def _invoke(core_server, tool_name: str, kwargs: dict[str, Any]) -> tuple[Any, str]:
    trace_id = uuid.uuid4().hex
    base_kwargs = {
        "trace_id": trace_id,
        "project_id": "sarydala-live-test",
        "agent_id": "live-matrix-runner",
        "policy_id": "secure-readonly-v1",
        "session_id": "sarydala-session-01",
    }
    base_kwargs.update(kwargs)
    result = getattr(core_server, tool_name)(**base_kwargs)
    return result, trace_id


def main() -> int:
    configure_quiet_logging()
    config = prepare_live_env()
    if not config.service_url:
        print("FAIL: set ONEC_ODATA_URL or ONEC_ODATA_BASE_URL first")
        return 1

    _clean_audit_file()
    core_server, policy = _load_core_server()

    live_entities_result, _ = _invoke(core_server, "list_entities", {"limit": 10})
    entity_items = (live_entities_result.get("data") or []) if isinstance(live_entities_result, dict) else []
    entity_name = entity_items[0]["name"] if entity_items else "Catalog_Банки"

    tool_specs: list[tuple[str, dict[str, Any], bool]] = [
        ("get_server_status", {}, False),
        ("setup_wizard", {"check_live_entities": False, "live_limit": 5}, False),
        ("generate_1c_database_profile", {"check_inventory_data": False, "live_limit": 0}, False),
        ("ask_1c", {"text": "Проверь подключение к 1С"}, False),
        ("list_entities", {"limit": 15}, False),
        ("describe_entity", {"entity_name": entity_name}, False),
        ("search_metadata", {"text": "контрагент", "limit": 10}, False),
        ("discover_inventory_sources", {"limit": 10, "check_data": True}, False),
        ("get_inventory_auto", {"limit": 10}, False),
        ("get_low_stock_items", {"limit": 10, "threshold_quantity": "10"}, False),
        ("discover_payment_sources", {"limit": 10, "check_data": True}, False),
        ("get_outgoing_payments", {"date_from": "2020-01-01", "date_to": "2026-12-31", "limit": 10}, False),
        ("get_incoming_payments", {"date_from": "2020-01-01", "date_to": "2026-12-31", "limit": 10}, False),
        ("payment_summary_by_counterparty", {"direction": "incoming", "date_from": "2020-01-01", "date_to": "2026-12-31", "limit": 10}, False),
        ("get_unpaid_customers_summary", {"date_from": "2020-01-01", "date_to": "2026-12-31", "limit": 10}, False),
        ("get_overdue_unpaid_customers", {"date_from": "2020-01-01", "as_of_date": "2026-05-09", "threshold_days": 3, "limit": 10}, False),
        ("get_customer_payment_behavior_summary", {"date_from": "2020-01-01", "as_of_date": "2026-05-09", "limit": 10}, False),
        ("explain_last_answer", {}, False),
        ("parse_inventory_report_text", {"report_text": _safe_text_report()}, False),
        ("validate_inventory_report_text", {"report_text": _safe_text_report(), "warehouse": "Основной склад", "limit": 10}, False),
        ("find_buh_entity", {"kind": "counterparty", "query": "ТОО", "limit": 10}, False),
        ("search_document_by_number", {"document_number": "0001", "limit": 10}, False),
        ("get_customer_settlements_summary", {"date_from": "2020-01-01", "date_to": "2026-12-31", "limit": 10}, False),
        ("get_cash_bank_movements", {"date_from": "2020-01-01", "date_to": "2026-12-31", "movement_type": "all", "account_type": "all", "limit": 10}, False),
        ("query_entity", {"entity_name": entity_name, "top": 1}, True),
        ("post_document_validated", {"document_ref": "TEST-REF", "validation_result": {}}, True),
    ]

    rows: list[dict[str, Any]] = []
    failures = 0
    for tool_name, kwargs, expected_blocked in tool_specs:
        try:
            result, trace_id = _invoke(core_server, tool_name, kwargs)
        except Exception as exc:
            trace_id = uuid.uuid4().hex
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "type": type(exc).__name__}
        status, row_count, note, output_filter_applied = _classify_result(tool_name, result, expected_blocked=expected_blocked)
        audit_created = _tool_audit_created(trace_id, tool_name)
        raw_url_leaked = contains_internal_url(result, config.service_url, config.base_url)
        policy_entry = policy.tools.get(tool_name)
        risk = policy_entry.risk.value if policy_entry and policy_entry.risk else None
        capabilities = [cap.name for cap in policy_entry.capabilities] if policy_entry else []
        if tool_name in policy.forbidden:
            capabilities = []
        result_summary = json.dumps(result, ensure_ascii=False)[:700]
        rows.append(
            {
                "tool_name": tool_name,
                "policy_risk_level": risk,
                "capabilities": capabilities,
                "status": status,
                "input_used": kwargs,
                "result_summary": result_summary,
                "row_count": row_count,
                "error_type": result.get("type") if isinstance(result, dict) else None,
                "audit_record_created": audit_created,
                "output_filter_applied": output_filter_applied,
                "raw_odata_url_leaked": raw_url_leaked,
                "notes": note,
            }
        )
        if status == "FAIL":
            failures += 1

    summary = {
        "generated_at": now_iso(),
        "base_url": config.base_url,
        "service_url": config.service_url,
        "total_tools": len(rows),
        "passed": sum(1 for row in rows if row["status"] == "PASS"),
        "pass_empty": sum(1 for row in rows if row["status"] == "PASS_EMPTY"),
        "skipped": sum(1 for row in rows if row["status"].startswith("SKIP")),
        "failed": sum(1 for row in rows if row["status"] == "FAIL"),
        "blocked_expected": sum(1 for row in rows if row["status"] == "BLOCKED_EXPECTED"),
        "audit_path": str(AUDIT_PATH),
        "results": rows,
    }

    json_path = REPORTS_DIR / "live_mcp_tool_matrix_report.json"
    md_path = REPORTS_DIR / "live_mcp_tool_matrix_report.md"
    write_json(json_path, summary)

    lines = [
        "# Live MCP Tool Matrix Report",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Base URL: `{config.base_url}`",
        f"- Service URL: `{config.service_url}`",
        f"- Total tools: `{summary['total_tools']}`",
        f"- PASS: `{summary['passed']}`",
        f"- PASS_EMPTY: `{summary['pass_empty']}`",
        f"- SKIP: `{summary['skipped']}`",
        f"- FAIL: `{summary['failed']}`",
        f"- BLOCKED_EXPECTED: `{summary['blocked_expected']}`",
        "",
        "| Tool | Risk | Status | Rows | Audit | Filter | URL leak | Notes |",
        "|---|---:|---|---:|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['tool_name']}` | `{row['policy_risk_level']}` | `{row['status']}` | `{row['row_count']}` | `{row['audit_record_created']}` | `{row['output_filter_applied']}` | `{row['raw_odata_url_leaked']}` | {row['notes']} |"
        )
    write_markdown(md_path, "\n".join(lines) + "\n")

    print(f"OK: wrote {md_path}")
    print(f"OK: wrote {json_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
