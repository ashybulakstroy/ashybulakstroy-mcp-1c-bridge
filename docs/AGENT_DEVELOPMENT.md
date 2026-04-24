# Agent-oriented development layer

This project has a lightweight agent-development layer around the current read-only MCP runtime.

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

## Project scaffolding status

The module `init_project.py` exists as internal scaffolding logic, but it is not exposed as a public CLI command in the current package build.

So the current contract is:
- use MCP tools for inspection and validation;
- treat `init_project.py` as internal code unless a dedicated CLI/API is added later.

## Validate-before-post

High-risk posting operations must use validation before posting:

```text
parse_sales_invoice_text → normalize_sales_invoice → validate_sales_invoice → post_document_validated
```

In the current runtime, `post_document_validated` is a guardrail only. It rejects unvalidated calls and returns `validated_but_not_posted` instead of performing a real write to 1C.
