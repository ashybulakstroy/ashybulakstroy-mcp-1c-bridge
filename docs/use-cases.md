# Use cases

Документ описывает текущие read-only сценарии runtime.

Важно:
- это MCP backend, а не LLM client;
- для демонстраций и пилотов используйте только разрешённые read-only tools;
- blocked tools вроде `query_entity` и `post_document_validated` не должны использоваться как demo-path.

## Проверка подключения и базовой конфигурации

```text
Проверь подключение к 1С.
```

Рекомендуемый tool:
- `get_server_status`
- `setup_wizard`

## Паспорт базы

```text
Сделай паспорт базы 1С.
```

Рекомендуемый tool:
- `generate_1c_database_profile`

## Поиск опубликованных сущностей

```text
Какие таблицы есть в OData?
Найди в метаданных номенклатура.
```

Рекомендуемый tool:
- `list_entities`
- `search_metadata`
- `describe_entity`

## Остатки

```text
Покажи остатки товаров по складу Основной.
```

Рекомендуемый tool:
- `ask_1c`
- `get_inventory_auto`

## Низкие остатки

```text
Где заканчивается товар?
Какие товары меньше 5?
```

Рекомендуемый tool:
- `get_low_stock_items`

## Исходящие оплаты

```text
Кому мы заплатили за период 2026-04-01 2026-04-30
```

Рекомендуемый tool:
- `get_outgoing_payments`

## Входящие оплаты

```text
От кого получили деньги на дату 2026-04-24
```

Рекомендуемый tool:
- `get_incoming_payments`

## Топ клиенты

```text
Топ клиенты за период 2026-04-01 2026-04-30
Кто больше всего нам заплатил?
```

Рекомендуемый tool:
- `payment_summary_by_counterparty`

## Неоплаченные клиенты

```text
Кто не оплатил?
Кому выставили счета, а они не оплатили?
```

Рекомендуемый tool:
- `get_unpaid_customers_summary`

## Просроченные должники

```text
Кто не оплатил в течение 3 календарных дней?
Должники старше 3 дней
```

Рекомендуемый tool:
- `get_overdue_unpaid_customers`

## Поведение оплаты клиентов

```text
Сколько дней обычно платит клиент?
Как быстро платят клиенты?
```

Рекомендуемый tool:
- `get_customer_payment_behavior_summary`

## Сверка

```text
Сверь остатки с этим отчётом: ...
```

Рекомендуемый tool:
- `validate_inventory_report_text`

## Demo docs

Для пошаговой демонстрации и готовых prompt’ов см.:
- `docs/DEMO_READONLY_SECURE_MODE.md`
- `docs/DEMO_PROMPTS.md`
