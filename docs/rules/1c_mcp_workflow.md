# MCP workflow для 1С

## Роли MCP

- Tools — выполняют действия: inspect, normalize, validate, create, post.
- Resources — дают состояние: metadata, documents, catalogs, capabilities, health.
- Prompts — задают режим работы ассистента: бухгалтер, ревьюер, тестировщик, аналитик.

## Безопасный сценарий создания реализации

```text
1. parse_sales_invoice_text
2. normalize_sales_invoice
3. validate_sales_invoice
4. create_sales_invoice_normalized
5. post_document_validated
```

## Запрет

`post_document` нельзя вызывать без результата `validate_sales_invoice.valid = true`, кроме ручного режима администратора.
