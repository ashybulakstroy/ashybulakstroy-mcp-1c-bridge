# Use cases

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

## Сверка

```text
Сверь остатки с этим отчётом: ...
```

Рекомендуемый tool:
- `validate_inventory_report_text`
