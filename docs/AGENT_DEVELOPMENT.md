# Agent-oriented development layer

This project now has a lightweight agent-development layer inspired by capability-based 1C automation practices.

## Capability registry

Capabilities are stable business meanings above raw MCP tools.

Current registry:

- `metadata.inspect`
- `stock.read`
- `stock.validate_before_sale`
- `money.read`
- `documents.create`
- `documents.post`

MCP tools:

- `list_capabilities`
- `get_capability`

Resource:

- `buh://capabilities`

## Project knowledge

Run:

```bash
ashybulak-1c-bridge init-project
```

It creates:

```text
project_knowledge/
├── 1c_kazakhstan.md
├── business_rules.md
├── roles_and_permissions.md
├── document_mapping.md
└── odata_entities.md
```

These files are meant to be committed to the project repository and filled after running `inspect` against the real 1C base.

## Contract tests

`init-project` also creates:

```text
docs/specs/create_sales_invoice.md
tests/contracts/test_validate_before_post.py
```

These are skeletons for making dangerous write/post operations testable before touching production 1C.

## Validate-before-post

High-risk posting operations must use validation before posting:

```text
validate_sales_invoice → create_sales_invoice → post_document_validated
```

For a direct post of an existing document, use:

```text
post_document_validated
```

This calls the expected RPC method:

```text
documents.validate_before_post
```

and only then calls the actual posting method.
