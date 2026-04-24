# Полная архитектура AshybulakStroy MCP 1C Bridge

## Текущие слои

```text
MCP runtime
├── Tools
├── Resources
├── Prompts
└── Application core
    ├── OData client
    ├── Inventory discovery heuristics
    ├── Validation and reconciliation
    ├── Recipes / SQLite memory
    └── Normalization and guardrails
```

## Runtime vs future extension

Текущее состояние:
- основной transport: stdio;
- основной источник данных: OData;
- бизнес-сценарий production-ready: read-only inspection и inventory workflows;
- нормализация и валидация документов встроены;
- фактическая запись в 1С по умолчанию выключена.

Будущее расширение:
- отдельный RPC adapter для create/post операций;
- отдельный HTTP-service contract на стороне 1С;
- включение write-сценариев только после validate-before-post.

## Модули

```text
capabilities/       # business capability registry
docs/rules/         # operational rules for assistants and developers
normalization/      # free-text to draft payload normalization
prompts/            # reusable prompt assets
templates/          # payload templates
validation_rules/   # guardrails before write/post
```

## Безопасный pipeline документов

```text
parse_sales_invoice_text
-> normalize_sales_invoice
-> validate_sales_invoice
-> post_document_validated
```

Последний шаг в текущей сборке не проводит документ, а только блокирует небезопасный вызов без успешной валидации.
