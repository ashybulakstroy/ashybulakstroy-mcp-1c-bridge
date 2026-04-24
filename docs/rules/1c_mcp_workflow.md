# MCP workflow для 1С

## Роли MCP

- Tools — выполняют действия: inspect, discover, normalize, validate, compare.
- Resources — дают состояние: entities, capabilities, health, templates.
- Prompts — задают режим работы ассистента: бухгалтер, ревьюер, тестировщик, аналитик.

## Безопасный сценарий для документов

```text
1. parse_sales_invoice_text
2. normalize_sales_invoice
3. validate_sales_invoice
4. post_document_validated
```

## Запрет

Нельзя выполнять write/post-операции без результата `validate_sales_invoice.valid = true`.

В текущем runtime даже успешная валидация не означает фактическое проведение документа: для этого нужен отдельный RPC/HTTP adapter.
