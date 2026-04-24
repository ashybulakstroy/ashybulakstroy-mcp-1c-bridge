# Business modules: current runtime view

The repository contains several domain-oriented modules, but the public MCP runtime is currently centered around OData inspection, inventory workflows and document guardrails.

## 1. Metadata and OData exploration

Primary tools:
- `setup_wizard`
- `generate_1c_database_profile`
- `list_entities`
- `describe_entity`
- `sample_entity`
- `search_metadata`
- `explore_live_entities`

Purpose:
- inspect published OData objects;
- understand real entity names and fields before building recipes or integrations;
- avoid hardcoded assumptions about specific 1C metadata names.

## 2. Inventory and warehouse workflows

Primary tools:
- `discover_inventory_sources`
- `get_inventory_auto`
- `get_low_stock_items`
- `validate_inventory_report_text`
- `compare_inventory_rows`

Purpose:
- detect likely inventory sources from `$metadata`;
- normalize rows to a stable `item / warehouse / quantity / amount` shape;
- reconcile MCP data against a copied official 1C report.

Important constraint:
- `get_inventory_auto` is heuristic;
- official 1C reporting remains the source of truth.

## 3. Document normalization and validation

Primary tools:
- `parse_sales_invoice_text`
- `find_buh_entity`
- `normalize_sales_invoice`
- `validate_sales_invoice`
- `post_document_validated`

Purpose:
- transform free text into a draft payload;
- resolve candidate entities in 1C;
- validate the payload before any future write path;
- block unsafe posting when validation is missing.

Current limitation:
- the runtime does not create or post documents in 1C by default;
- `post_document_validated` is a guardrail, not a write operation.
