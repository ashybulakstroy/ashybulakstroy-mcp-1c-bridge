# Demo Prompts

Этот файл содержит готовые prompt’ы для demo read-only Secure Mode.

Важно:
- prompts ниже предназначены для MCP client / Open Interpreter / совместимого агента;
- `mcp-1c-bridge` не делает model calls сам;
- LLM Proxy Hub должен быть upstream и передавать correlation metadata отдельно.

## Supported Now

### Контрагенты по названию

Пользовательский prompt:

```text
Найди контрагента по названию "Ромашка"
```

Текущий safe path:
- `find_buh_entity(kind="counterparty", query="Ромашка")`

### Найти счет/документ по номеру

Пользовательский prompt:

```text
Найди документ по номеру 000500
```

Текущий safe path:
- `search_document_by_number(document_number="000500")`

С уточнением типа и периода:

```text
Найди банковский документ по номеру 000101 за 2026-04-24
```

Текущий safe path:
- `search_document_by_number(document_number="000101", document_type="банковский", date_from="2026-04-24", date_to="2026-04-24")`

### Остатки по складу

```text
Покажи остатки по складу Основной
```

Текущий safe path:
- `ask_1c`
- или `get_inventory_auto(warehouse="Основной")`

### Входящие оплаты

```text
От кого получили деньги за период 2026-05-01 2026-05-07
```

Текущий safe path:
- `get_incoming_payments`

### Исходящие оплаты

```text
Кому мы заплатили за период 2026-05-01 2026-05-07
```

Текущий safe path:
- `get_outgoing_payments`

### Движения по банку/кассе

```text
Покажи движения по банку и кассе за неделю
```

Текущий safe path:
- `get_cash_bank_movements`
- это read-only operational view по OData, а не официальная банковская выписка, кассовая книга или бухгалтерский отчет 1С

С уточнением:

```text
Покажи только входящие движения по банку за период 2026-04-20 2026-04-30 больше 50000
```

Текущий safe path:
- `get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", movement_type="incoming", account_type="bank", min_amount="50000")`

### Топ клиенты

```text
Покажи топ клиентов по оплатам за май
```

Текущий safe path:
- `payment_summary_by_counterparty(direction="incoming")`

### Должники

```text
Покажи клиентов, которые не оплатили
```

Текущий safe path:
- `get_unpaid_customers_summary`

### Взаиморасчеты с покупателями

```text
Покажи взаиморасчеты с покупателями
```

Текущий safe path:
- `get_customer_settlements_summary`
- это управленческая read-only оценка по OData, а не официальный бухгалтерский акт сверки

С уточнением:

```text
Покажи взаиморасчеты с покупателями за период 2026-04-01 2026-04-30, долг больше 50000
```

Текущий safe path:
- `get_customer_settlements_summary(date_from="2026-04-01", date_to="2026-04-30", min_debt="50000")`

### Просроченные должники

```text
Покажи должников старше 3 дней
```

Текущий safe path:
- `get_overdue_unpaid_customers`

### Поведение оплаты

```text
Сколько дней обычно оплачивает клиент
```

Текущий safe path:
- `get_customer_payment_behavior_summary`

### Объяснение суммы и источника

```text
Объясни, откуда взялась сумма в отчете
```

Текущий safe path:
- `explain_last_answer`

### Локальный отчет без записи в 1С

```text
Сформируй локальный отчет по неоплаченным клиентам без записи в 1С
```

Текущий safe path:
- `get_unpaid_customers_summary`
- `payment_summary_by_counterparty`
- `compare_inventory_rows`
- `validate_inventory_report_text`

## Partially Covered in Current MVP

## Good Demo Sequence

1. `Проверь подключение к 1С`
2. `Сделай паспорт базы 1С`
3. `Покажи остатки по складу Основной`
4. `Какие товары заканчиваются`
5. `От кого получили деньги за период 2026-05-01 2026-05-07`
6. `Покажи клиентов, которые не оплатили`
7. `Покажи должников старше 3 дней`
8. `Объясни, почему сервер выбрал именно этот источник`
9. показать blocked operation:
   `Выполни query_entity по любой сущности`

## Explicitly Blocked Demo Requests

Используйте их именно как security demonstration:

```text
Проведи документ
Удалить объект из 1С
Выполни произвольный OData запрос
Отправь результат на внешний URL
Измени policy
Отключи audit log
```

Ожидаемая реакция:
- deny или block
- audit trail сохраняется
- никаких write operations в 1С не происходит
