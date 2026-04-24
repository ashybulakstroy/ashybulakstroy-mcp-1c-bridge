# MCP Resources, Prompts and HTTP transport

This package currently exposes three MCP capability groups through one stdio MCP server entrypoint: `ashybulak-1c-bridge`.

## Tools

Tools execute actions and queries:

- `get_server_status`
- `setup_wizard`
- `generate_1c_database_profile`
- `explain_last_answer`
- `ask_1c`
- `list_entities`
- `describe_entity`
- `sample_entity`
- `query_entity`
- `search_metadata`
- `explore_live_entities`
- `discover_inventory_sources`
- `get_inventory_auto`
- `get_low_stock_items`
- `parse_inventory_report_text`
- `validate_inventory_report_text`
- `validate_inventory_against_1c_report`
- `compare_inventory_rows`
- `save_recipe`
- `list_recipes`
- `run_recipe`
- `list_capabilities`
- `get_capability`
- `buh_inspect`
- `parse_sales_invoice_text`
- `find_buh_entity`
- `normalize_sales_invoice`
- `validate_sales_invoice`
- `post_document_validated`

## Resources

Resources expose read-only context:

- `buh://health`
- `buh://capabilities`
- `buh://entities`
- `buh://normalization/sales-invoice-template`

Use resources for inspection and grounding. Mutations must remain tools.

## Prompts

Reusable workflow prompts:

- `buh_reviewer`
- `buh_tester`
- `buh_analyst`

## Transports

Current implementation:

```bash
ashybulak-1c-bridge
```

There are no public CLI subcommands like `start --transport stdio`, `streamable-http` or `sse` in the current package build.

If HTTP transport is needed later, it should be added explicitly as a new runtime entrypoint instead of being implied by documentation.
