# AshybulakStroy MCP 1C Bridge

AshybulakStroy MCP 1C Bridge — MCP-сервер для безопасного AI-доступа к данным 1С:Бухгалтерия для Казахстана 3.0 через OData.

Текущий фокус проекта:
- read-only доступ к опубликованным OData-сущностям 1С;
- поиск и объяснение источников остатков;
- получение остатков и низких остатков;
- сверка MCP-данных с отчётом 1С, вставленным обычным текстом;
- guardrail-пайплайн для нормализации и валидации документов без фактической записи в 1С.

## Что умеет сервер

Основные MCP tools:
- `get_server_status`
- `setup_wizard`
- `generate_1c_database_profile`
- `ask_1c`
- `list_entities`
- `describe_entity`
- `sample_entity`
- `query_entity`
- `search_metadata`
- `explore_live_entities`
- `discover_inventory_sources`
- `get_inventory_auto`
- `get_low_stock_items`
- `parse_inventory_report_text`
- `validate_inventory_report_text`
- `save_recipe`
- `list_recipes`
- `run_recipe`
- `list_capabilities`
- `get_capability`
- `buh_inspect`
- `parse_sales_invoice_text`
- `find_buh_entity`
- `normalize_sales_invoice`
- `validate_sales_invoice`
- `post_document_validated`

MCP resources:
- `buh://health`
- `buh://capabilities`
- `buh://entities`
- `buh://normalization/sales-invoice-template`

MCP prompts:
- `buh_reviewer`
- `buh_tester`
- `buh_analyst`

## Установка

```bash
git clone https://github.com/ashybulakstroy/ashybulakstroy-mcp-1c-bridge.git
cd ashybulakstroy-mcp-1c-bridge
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

На Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

Рекомендуемая версия Python:
- оптимально: `3.11.x`
- поддерживается: `3.10+`
- `3.12` тоже подходит и используется в текущем локальном окружении

## Настройка `.env`

```env
ONEC_ODATA_URL=http://localhost/AccountingKazakhstan/odata/standard.odata
ONEC_USERNAME=odata_user
ONEC_PASSWORD=secret
ONEC_TIMEOUT_SECONDS=60
ONEC_VERIFY_SSL=true
BRIDGE_DB_PATH=./bridge_knowledge.sqlite3
BRIDGE_MAX_TOP=500
```

Пользователь 1С для OData должен быть отдельным и read-only.

## Запуск

Пакет публикует один script-entrypoint:

```bash
ashybulak-1c-bridge
```

Это stdio MCP server. Отдельных CLI-подкоманд вроде `start`, `inspect` или `init-project` в текущей сборке нет.

## Подключение к MCP-клиенту

```json
{
  "mcpServers": {
    "ashybulakstroy-1c": {
      "command": "ashybulak-1c-bridge",
      "env": {
        "ONEC_ODATA_URL": "http://localhost/AccountingKazakhstan/odata/standard.odata",
        "ONEC_USERNAME": "readonly_user",
        "ONEC_PASSWORD": "password",
        "ONEC_TIMEOUT_SECONDS": "60",
        "ONEC_VERIFY_SSL": "true",
        "BRIDGE_MAX_TOP": "500"
      }
    }
  }
}
```

## Типовой первый сценарий

Пользователь может работать обычным текстом через `ask_1c`:

```text
Проверь подключение к 1С.
Сделай паспорт базы 1С.
Найди источники остатков.
Покажи остатки товаров.
Где заканчивается товар?
Объясни последний ответ.
```

Для более точной диагностики можно вызывать tools напрямую:
- `setup_wizard`
- `generate_1c_database_profile`
- `discover_inventory_sources`
- `get_inventory_auto`
- `get_low_stock_items`

## Сверка с отчётом 1С

1. В 1С сформируйте официальный отчёт, например «Материальная ведомость».
2. Поставьте те же фильтры, что и в MCP-запросе.
3. Скопируйте табличную часть отчёта.
4. Передайте текст в `validate_inventory_report_text`.

Пример:

```text
Сверь остатки с этим отчётом:
Номенклатура    Склад           Количество    Сумма
Цемент М400     Основной склад  100           250000
Песок           Основной склад  50            30000
```

## Ограничения и безопасность

- сервер ориентирован на чтение данных через OData;
- сервер не создаёт и не проводит документы в текущем runtime;
- `post_document_validated` является guardrail-заглушкой и возвращает статус `validated_but_not_posted`;
- результаты `get_inventory_auto` и `get_low_stock_items` эвристические и должны подтверждаться отчётом 1С;
- внутренние имена объектов 1С нельзя жёстко зашивать без проверки через `$metadata`.

## Структура проекта

```text
src/ashybulakstroy_mcp_1c_bridge/
  core_server.py     # основная реализация MCP tools/resources/prompts
  mcp/server.py      # стабильный facade entrypoint
  odata.py           # OData client, metadata discovery, inventory heuristics
  knowledge.py       # SQLite recipe storage
  validation.py      # parsing and reconciliation
  normalization/     # document draft normalization helpers
  validation_rules/  # document/business guardrails
```

## Тестирование

```bash
pip install -e .[dev]
python -m pytest -q
```

GitHub Actions прогоняет тесты на `Python 3.10`, `3.11` и `3.12`.

Подробнее:
- `docs/testing.md`
- `docs/architecture.md`
- `docs/MCP_RESOURCES_PROMPTS_HTTP.md`

## Статус проекта

Проект находится в рабочем состоянии как MCP read-only bridge для OData-инспекции, остатков и сверки.

Слой нормализации и валидации документов уже встроен, но реальная запись и проведение в 1С требуют отдельного RPC-адаптера и явного расширения текущего runtime.

## Лицензия

MIT
