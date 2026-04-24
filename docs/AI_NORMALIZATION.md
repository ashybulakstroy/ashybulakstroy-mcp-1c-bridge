# AI-нормализация входных данных

AI-нормализация — это безопасный слой между человеческим запросом и записью в 1С.
Он не создаёт документ сразу. Сначала он превращает текст/черновой payload в структуру с реальными `Ref_Key` из 1С.

## Pipeline

```text
user text / draft payload
  ↓
parse_sales_invoice_text
  ↓
find_buh_entity / OData catalog search
  ↓
normalize_sales_invoice
  ↓
validate + optional stock check
  ↓
post_document_validated
```

## MCP tools

- `parse_sales_invoice_text` — разбирает свободный текст в черновой payload.
- `find_buh_entity` — ищет кандидатов в справочниках: `counterparty`, `item`, `warehouse`.
- `normalize_sales_invoice` — подставляет реальные ссылки 1С и возвращает `issues`.
- `validate_sales_invoice` — проверяет структуру и обязательные поля.
- `post_document_validated` — guardrail, который не даёт вызывать post без успешной валидации.

## Safety rules

- Если есть `not_found`, `ambiguous_match`, `missing_value`, `missing_items` — документ не создаётся.
- Если найдено несколько похожих кандидатов — пользователь должен выбрать вариант.
- Для записи в 1С используется RPC. OData используется только для поиска и чтения.
- В текущем runtime фактическая запись и проведение не выполняются.

## Example payload

```json
{
  "counterparty": "ТОО Ромашка",
  "warehouse": "Основной склад",
  "items": [
    {"name": "Цемент", "quantity": 20, "unit": "мешок", "price": 2500}
  ]
}
```

## Example free text

```text
Ромашка: цемент 20 мешков по 2500
```

## Output shape

```json
{
  "ok": true,
  "normalized": {
    "document_type": "РеализацияТоваровУслуг",
    "counterparty": {"ref": "...", "name": "ТОО Ромашка"},
    "warehouse": {"ref": "...", "name": "Основной склад"},
    "items": [
      {"item_ref": "...", "item_name": "Цемент", "quantity": 20, "price": 2500}
    ]
  },
  "issues": []
}
```
