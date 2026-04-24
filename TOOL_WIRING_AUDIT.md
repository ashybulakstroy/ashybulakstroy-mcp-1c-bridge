# Tool Wiring Audit - rebuilt from 216KB base

Base archive: `ashybulakstroy-mcp-1c-bridge-v0_8-restored-platform.zip` (~216KB).

## Canonical server
- Real implementation: `src/ashybulakstroy_mcp_1c_bridge/core_server.py`
- Facade: `src/ashybulakstroy_mcp_1c_bridge/mcp/server.py`
- CLI: `ashybulakstroy_mcp_1c_bridge.mcp.server:main`

## Registered MCP tools in real core_server.py

Total decorators: **29**

- get_server_status
- setup_wizard
- generate_1c_database_profile
- explain_last_answer
- ask_1c
- list_entities
- describe_entity
- sample_entity
- query_entity
- search_metadata
- explore_live_entities
- discover_inventory_sources
- get_inventory_auto
- get_low_stock_items
- parse_inventory_report_text
- validate_inventory_report_text
- validate_inventory_against_1c_report
- compare_inventory_rows
