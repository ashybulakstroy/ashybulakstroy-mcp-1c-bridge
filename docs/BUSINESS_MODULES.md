# Business modules: warehouse, money, documents

This package now has three business domains on top of the unified 1C client.

## 1. Warehouse / stock

MCP tools:

| Tool | Channel | Purpose |
|---|---|---|
| `get_warehouses` | OData | List/search warehouses (`Catalog_Склады`) |
| `find_item` | OData | Search items/nomenclature (`Catalog_Номенклатура`) |
| `get_stock_balance` | RPC by default, optional OData register | Stock balances |
| `check_stock_before_sale` | RPC | Validate available stock before sale |

RPC methods expected on 1C side:

```text
warehouse.get_stock_balance
warehouse.check_stock_before_sale
```

`get_stock_balance` can also read an OData register directly if you pass `register_entity`, for example after running `ashybulak-1c-bridge inspect` and finding the real accumulation register name.

## 2. Money

MCP tools:

| Tool | Channel | Purpose |
|---|---|---|
| `get_cash_balance` | RPC | Cash balance |
| `get_bank_balance` | RPC | Bank account balance |
| `get_counterparty_debt` | RPC | Receivables/payables |
| `get_unpaid_invoices` | RPC | Unpaid invoices/sales documents |
| `find_payments` | RPC | Search payments |

RPC methods expected on 1C side:

```text
money.get_cash_balance
money.get_bank_balance
money.get_counterparty_debt
money.get_unpaid_invoices
money.find_payments
```

## 3. Documents

MCP tools:

| Tool | Channel | Purpose |
|---|---|---|
| `find_documents` | OData | Search/list documents |
| `create_sales_invoice` | RPC | Create `РеализацияТоваровУслуг` |
| `create_purchase_invoice` | RPC | Create `ПоступлениеТоваровУслуг` |
| `post_document` | RPC | Post a document |
| `unpost_document` | RPC | Unpost a document |
| `get_document_status` | RPC | Get document status |

RPC methods expected on 1C side:

```text
documents.create
documents.post
documents.unpost
documents.get_status
```

## Discovery first

Before hardcoding document/register names, run:

```bash
ashybulak-1c-bridge inspect
```

The command checks RPC/OData and lists published OData documents, catalogs and registers from `$metadata`.
