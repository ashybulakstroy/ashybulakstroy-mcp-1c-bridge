# Architecture

```text
1С:Бухгалтерия для Казахстана 3.0
        │ OData
        ▼
OneCODataClient
        │
Discovery + Inventory Heuristics
        │
KnowledgeStore / SQLite Recipes
        │
FastMCP runtime
        │
AI Client
        │
User
```

## Components

- `core_server.py` — основная реализация tools, resources и prompts.
- `mcp/server.py` — фасадный entrypoint для стабильного импорта пакета.
- `odata.py` — OData client, discovery, поиск источников остатков, нормализация inventory rows.
- `knowledge.py` — хранение recipes и истории запусков в SQLite.
- `validation.py` — парсинг табличного текста и сверка строк.
- `normalization/` — подготовка document drafts из свободного текста и payload.
- `validation_rules/` — бизнес- и document-guardrails.
- `config.py` — загрузка `.env` через `ONEC_*` и `BRIDGE_*` настройки.

## Runtime model

- единственный публикуемый CLI-entrypoint: `ashybulak-1c-bridge`;
- транспорт в текущей реализации: stdio MCP server;
- чтение данных: OData;
- запись/проведение: не выполняются в runtime по умолчанию, даже если validation успешна.

## Main flow

```text
setup_wizard / buh_inspect
        ↓
metadata discovery
        ↓
inventory source detection
        ↓
get_inventory_auto / get_low_stock_items
        ↓
validate_inventory_report_text
```
