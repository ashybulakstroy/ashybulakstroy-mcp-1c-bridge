# Live MCP Tool Matrix Report

- Generated: `2026-05-09T16:27:41.203382+05:00`
- Base URL: `http://192.168.1.183/SaryDala`
- Service URL: `http://192.168.1.183/SaryDala/odata/standard.odata`
- Total tools: `26`
- PASS: `24`
- PASS_EMPTY: `0`
- SKIP: `0`
- FAIL: `0`
- BLOCKED_EXPECTED: `2`

| Tool | Risk | Status | Rows | Audit | Filter | URL leak | Notes |
|---|---:|---|---:|---|---|---|---|
| `get_server_status` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `setup_wizard` | `L0` | `PASS` | `5` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `generate_1c_database_profile` | `L0` | `PASS` | `10` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `ask_1c` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `list_entities` | `L0` | `PASS` | `15` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `describe_entity` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `search_metadata` | `L0` | `PASS` | `10` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `discover_inventory_sources` | `L0` | `PASS` | `10` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `get_inventory_auto` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `get_low_stock_items` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `discover_payment_sources` | `L0` | `PASS` | `10` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `get_outgoing_payments` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `get_incoming_payments` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `payment_summary_by_counterparty` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `get_unpaid_customers_summary` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `get_overdue_unpaid_customers` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `get_customer_payment_behavior_summary` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `explain_last_answer` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `parse_inventory_report_text` | `L1` | `PASS` | `2` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `validate_inventory_report_text` | `L1` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `find_buh_entity` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `search_document_by_number` | `L0` | `PASS` | `8` | `True` | `True` | `False` | Tool returned non-empty read-only result. |
| `get_customer_settlements_summary` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `get_cash_bank_movements` | `L0` | `PASS` | `0` | `True` | `True` | `False` | Tool returned structured non-tabular summary. |
| `query_entity` | `None` | `BLOCKED_EXPECTED` | `0` | `True` | `False` | `False` | tool is forbidden by policy denylist |
| `post_document_validated` | `None` | `BLOCKED_EXPECTED` | `0` | `True` | `False` | `False` | tool is forbidden by policy denylist |
