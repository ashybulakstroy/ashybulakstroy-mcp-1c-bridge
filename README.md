# AshybulakStroy MCP 1C Bridge

AshybulakStroy MCP 1C Bridge — MCP-сервер для безопасного AI-доступа к данным 1С:Бухгалтерия для Казахстана 3.0 через OData.

Текущий фокус проекта:
- read-only доступ к опубликованным OData-сущностям 1С;
- поиск и объяснение источников остатков;
- получение остатков и низких остатков;
- управленческие денежные отчёты по оплатам, топ-клиентам и должникам;
- сверка MCP-данных с отчётом 1С, вставленным обычным текстом;
- guardrail-пайплайн для нормализации и валидации документов без фактической записи в 1С.

## Secure Mode

Сервер работает в режиме `Secure Mode`:
- каждый MCP tool проходит policy decision перед исполнением;
- unknown tools запрещаются;
- forbidden tools блокируются;
- `L3` и `L4` операции блокируются всегда;
- каждый вызов записывается в append-only audit log;
- результат проходит output filter перед возвратом клиенту.

Основной принцип:

```text
AI может читать и объяснять данные 1С, но не должен иметь возможности сам себе выдать опасные разрешения или обойти policy.
```

## Read-only MVP

Текущая реализация соответствует Phase 1 Secure MVP:
- сервер ориентирован на read-only OData доступ;
- нет raw OData tool для агента;
- нет execute_1c_code;
- нет direct SQL;
- нет posting/delete операций;
- `post_document_validated` не проводит документ и в policy считается forbidden tool.

## Risk Levels

Phase 1 использует модель риска:
- `L0` — безопасное чтение и metadata inspection
- `L1` — локальная аналитика, explain/report/normalization без записи в 1С
- `L2` — потенциально чувствительные операции, в `read_only` режиме запрещены
- `L3` — критичные операции, всегда блокируются
- `L4` — явно опасные операции, всегда блокируются

Типичная интерпретация:
- `L0`: `list_entities`, `get_inventory_auto`, `get_incoming_payments`
- `L1`: `payment_summary_by_counterparty`, `get_unpaid_customers_summary`, `explain_last_answer`
- `L2+`: write/post/delete/direct access scenarios

## Capabilities

Security policy использует capabilities как уровень выше конкретных tool names.

Примеры текущих capabilities:
- `read_metadata`
- `read_inventory`
- `read_payments`
- `read_receivables`
- `read_documents`
- `create_local_report`
- `normalize_input`
- `manage_local_knowledge`
- `route_read_only_requests`

Tool без declared capabilities в policy не должен исполняться.

## Policy File

Политика лежит здесь:

```text
config/policy.yaml
```

Файл задаёт:
- `mode`
- `tools` allowlist
- `risk` per tool
- `capabilities` per tool
- `forbidden` denylist
- `output` settings

Основное поведение:
- default mode: `read_only`
- unknown tool: `deny`
- forbidden tool: `block`
- `L3`/`L4`: `block`
- `L2`: `deny` в `read_only`

## Audit Log

Audit log append-only с точки зрения агента.

Путь по умолчанию:

```text
audit/audit.jsonl
```

Каждая запись содержит:
- `timestamp`
- `actor`
- `tool`
- `risk`
- `capabilities`
- `decision`
- `policy_version`
- `duration_ms`
- `error`

Audit создаётся как для allowed, так и для denied/blocked вызовов.

## Output Filter

Перед возвратом результата MCP-клиенту сервер применяет output filter.

Phase 1 фильтр поддерживает:
- `max_rows`
- optional IIN/BIN masking
- optional bank account masking
- credential redaction
- blocking external URLs in payload-like output fields

Настройки фильтра также задаются в `config/policy.yaml`.

## Forbidden Operations

Phase 1 явно запрещает такие операции:
- `raw_odata`
- `query_entity`
- `execute_1c_code`
- `direct_sql`
- `delete_object`
- `post_document`
- `unpost_document`
- `change_posted_document`
- `change_closed_period`
- `external_http`
- `send_email`
- `upload_file`
- `disable_audit`
- `modify_policy`
- `post_document_validated`

Это ограничение policy-level и предназначено именно для Secure MVP.

## Architecture Flow

Текущий security flow:

```text
MCP client
  -> MCP tool call
  -> policy load
  -> allowlist / denylist check
  -> risk check
  -> capability check
  -> tool execution only if allowed
  -> output filter
  -> append-only audit log
  -> final MCP response
```

Высокоуровневая архитектура:

```text
User / MCP Client
        |
        v
FastMCP tools in core_server.py
        |
        v
SecureToolRunner
  -> policy_loader
  -> decision_engine
  -> output_filter
  -> audit_logger
        |
        v
Business read logic
  -> odata.py
  -> validation.py
  -> knowledge.py
        |
        v
1C OData
```

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
- `discover_payment_sources`
- `get_inventory_auto`
- `get_low_stock_items`
- `get_outgoing_payments`
- `get_incoming_payments`
- `payment_summary_by_counterparty`
- `get_unpaid_customers_summary`
- `get_overdue_unpaid_customers`
- `get_customer_payment_behavior_summary`
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

## Денежные сценарии для бизнеса

Сервер теперь поддерживает несколько read-only сценариев по оплатам и дебиторке:
- `кому мы заплатили` на дату или за период;
- `от кого мы получили деньги` на дату или за период;
- `топ клиенты` по входящим оплатам;
- `топ поставщики` по исходящим оплатам;
- `кто не оплатил` и `кому выставили счета, а они не оплатили`;
- `должники старше 3 дней`;
- `typical_payment_days` — сколько дней клиент обычно оплачивает счет.

Примеры фраз для `ask_1c`:

```text
Кому мы заплатили за период 2026-04-01 2026-04-30
От кого получили деньги на дату 2026-04-24
Топ клиенты за период 2026-04-01 2026-04-30
Кто не оплатил в течение 3 календарных дней
Сколько дней обычно платит клиент
```

Новые tools для этих сценариев:
- `discover_payment_sources`
- `get_outgoing_payments`
- `get_incoming_payments`
- `payment_summary_by_counterparty`
- `get_unpaid_customers_summary`
- `get_overdue_unpaid_customers`
- `get_customer_payment_behavior_summary`

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
- денежные отчёты по оплатам и дебиторке строятся по OData-эвристике и должны сверяться с отчётами 1С по взаиморасчётам;
- просрочка и `typical_payment_days` считаются FIFO-методом по контрагенту, это управленческий расчёт, а не официальный бухгалтерский регистр;
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

Проект находится в рабочем состоянии как MCP read-only bridge для OData-инспекции, остатков, денежных отчётов и сверки.

Слой нормализации и валидации документов уже встроен, но реальная запись и проведение в 1С требуют отдельного RPC-адаптера и явного расширения текущего runtime.

## Roadmap

See [Secure AI Bridge Roadmap](docs/ROADMAP_SECURE_AI_BRIDGE.md).


## Лицензия

MIT
