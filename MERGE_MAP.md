# Merge Map: v0.8 intelligence preserved + new platform layers

This archive uses `ashybulakstroy-mcp-1c-bridge-v0_8-testable.zip` as the base.
The original smart logic is preserved in-place.

## Preserved original v0.8 core

| Original file | Status | Responsibility |
|---|---:|---|
| `src/ashybulakstroy_mcp_1c_bridge/core_server.py` | preserved + appended | Main MCP server, inventory tools, recipes, explain trace |
| `src/ashybulakstroy_mcp_1c_bridge/odata.py` | preserved | OData metadata discovery, inventory source scoring, adaptive inventory reads |
| `src/ashybulakstroy_mcp_1c_bridge/validation.py` | preserved | Inventory report parsing/reconciliation |
| `src/ashybulakstroy_mcp_1c_bridge/knowledge.py` | preserved | SQLite recipes / reusable query memory |
| `tests/test_odata_inventory.py` | preserved | Tests for old OData inventory intelligence |
| `tests/test_validation.py` | preserved | Tests for old reconciliation logic |

## Added layers

| New location | Purpose |
|---|---|
| `capabilities/` | Capability registry: stock, metadata, normalization, documents |
| `normalization/legacy_sales_invoice.py` | Safe AI normalization over the original OData client |
| `validation_rules/` | New document guardrails without replacing old `validation.py` |
| `mcp/` | Resource/prompt modules from the later architecture, kept for extension |
| `buh/` | Later unified-client abstraction, kept as experimental/provider layer |
| `docs/rules/` | 1C anti-patterns, performance and MCP workflow rules |
| `prompts/` | Human-readable agent prompts |
| `templates/` | Sales invoice/payment templates |

## Important design choice

The old package name `ashybulakstroy_mcp_1c_bridge` remains the executable package.
Later code was imported under this package name to avoid creating a separate unconnected project.

`core_server.py` now exposes both old and new tools:

- Old: `setup_wizard`, `generate_1c_database_profile`, `ask_1c`, `get_inventory_auto`, `validate_inventory_against_1c_report`, `save_recipe`, `run_recipe`, `explain_last_answer`.
- New: `list_capabilities`, `get_capability`, `buh_inspect`, `parse_sales_invoice_text`, `find_buh_entity`, `normalize_sales_invoice`, `validate_sales_invoice`, `post_document_validated`.

The write/posting layer remains guarded. Real document posting must be connected to a real RPC adapter and should only run after normalization + validation.
