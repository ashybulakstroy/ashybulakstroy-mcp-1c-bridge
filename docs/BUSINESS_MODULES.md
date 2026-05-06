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

## 3. Money, payments and receivables

Primary tools:
- `discover_payment_sources`
- `get_outgoing_payments`
- `get_incoming_payments`
- `payment_summary_by_counterparty`
- `get_unpaid_customers_summary`
- `get_overdue_unpaid_customers`
- `get_customer_payment_behavior_summary`

Purpose:
- find likely OData entities for payments and sales documents;
- show who was paid and who paid us on a date or period;
- build top-clients and top-suppliers summaries;
- estimate unpaid customers from sales minus incoming payments;
- identify debtors overdue for more than N calendar days;
- estimate how many days each customer usually takes to pay.

Important constraint:
- these are management-style OData reports, not a replacement for official 1C mutual-settlement accounting;
- overdue and `typical_payment_days` are calculated with FIFO logic at counterparty level.

## 4. Document normalization and validation

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
