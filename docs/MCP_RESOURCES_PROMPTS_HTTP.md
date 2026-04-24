# MCP Resources, Prompts and HTTP transport

This package exposes three MCP capability groups:

## Tools

Tools execute actions and queries:

- `buh_ping`
- `get_balance`
- `get_counterparties`
- `get_catalog`
- `get_document_list`
- `get_stock_balance`
- `check_stock_before_sale`
- `get_cash_balance`
- `get_bank_balance`
- `get_counterparty_debt`
- `get_unpaid_invoices`
- `find_payments`
- `create_sales_invoice`
- `create_purchase_invoice`
- `post_document`
- `unpost_document`

## Resources

Resources expose read-only context:

- `buh://health`
- `buh://metadata`
- `buh://entities`
- `buh://catalogs`
- `buh://documents`

Use resources for inspection and grounding. Mutations must remain tools.

## Prompts

Reusable workflow prompts:

- `inspect_buh_database`
- `create_sales_invoice`
- `check_stock`
- `analyze_debt`

## Transports

Local MCP clients normally use stdio:

```bash
ashybulak-1c-bridge start --transport stdio
```

For service mode use Streamable HTTP when the installed MCP SDK supports it:

```bash
ashybulak-1c-bridge start --transport streamable-http
```

SSE is kept only for compatibility with older MCP clients:

```bash
ashybulak-1c-bridge start --transport sse
```
