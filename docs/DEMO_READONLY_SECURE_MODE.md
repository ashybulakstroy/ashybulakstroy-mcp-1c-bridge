# Demo: Read-only Secure Mode

Этот документ нужен для демонстрации проекта клиенту, интегратору 1С или новому разработчику.

Главная идея demo:
- AI может спрашивать 1С через MCP;
- bridge читает данные только в read-only режиме;
- каждый MCP tool проходит policy decision;
- вызовы логируются в append-only audit log;
- blocked operations показываются отдельно как часть Secure Mode.

## Prerequisites

- Windows PowerShell или совместимая shell-среда
- Python `3.11` или `3.12`
- настроенная публикация 1С OData
- отдельный read-only пользователь 1С для OData
- локально созданное окружение `.venv`

## Configure Environment

Минимальные переменные:

```env
ONEC_ODATA_URL=http://localhost/AccountingKazakhstan/odata/standard.odata
ONEC_USERNAME=readonly_user
ONEC_PASSWORD=secret
ONEC_TIMEOUT_SECONDS=60
ONEC_VERIFY_SSL=true
BRIDGE_DB_PATH=./bridge_knowledge.sqlite3
BRIDGE_MAX_TOP=500
BRIDGE_POLICY_PATH=./config/policy.yaml
BRIDGE_AUDIT_LOG_PATH=./audit/audit.jsonl
```

Пояснения:
- `ONEC_ODATA_URL` — URL опубликованной базы 1С
- `ONEC_USERNAME` / `ONEC_PASSWORD` — учётка OData
- `BRIDGE_POLICY_PATH` — policy allowlist/denylist/risk/capabilities
- `BRIDGE_AUDIT_LOG_PATH` — append-only audit log

## Start MCP Server

```powershell
cd C:\Work\Projects\Prj_9_MCP_1C_Ashybulak
.\.venv\Scripts\Activate.ps1
ashybulak-1c-bridge
```

Или без активации:

```powershell
C:\Work\Projects\Prj_9_MCP_1C_Ashybulak\.venv\Scripts\ashybulak-1c-bridge.exe
```

Ожидаемое поведение:
- сервер стартует в `stdio` режиме;
- печатает startup logs в `stderr`;
- ждёт MCP client;
- ничего не пишет в 1С.

## Run Tests

```powershell
cd C:\Work\Projects\Prj_9_MCP_1C_Ashybulak
.\.venv\Scripts\python.exe -m pytest
```

Ожидаемый статус на текущий момент:
- `31 passed`

## Verify Audit Log

```powershell
cd C:\Work\Projects\Prj_9_MCP_1C_Ashybulak
.\.venv\Scripts\python.exe scripts\verify_audit_log.py
```

Скрипт проверяет обязательные поля:
- `timestamp`
- `trace_id`
- `actor`
- `tool`
- `risk`
- `capabilities`
- `decision`
- `policy_version`
- `duration_ms`

## Current Demo-ready Tool Matrix

| Tool | What it does | Risk | Capabilities | Demo useful | Blocked by policy | Docs aligned |
|---|---|---:|---|---|---|---|
| `get_server_status` | Проверяет config без чтения бизнес-данных | L0 | `read_metadata` | yes | no | yes |
| `setup_wizard` | Проверяет `.env`, OData, metadata, кандидатов источников | L0 | `read_metadata` | yes | no | yes |
| `generate_1c_database_profile` | Строит паспорт опубликованной базы | L0 | `read_metadata` | yes | no | yes |
| `ask_1c` | Роутит простые read-only запросы обычным текстом | L1 | `route_read_only_requests` | yes | no | yes |
| `list_entities` | Показывает опубликованные OData сущности | L0 | `read_metadata` | yes | no | yes |
| `describe_entity` | Описывает поля одной сущности | L0 | `read_metadata` | yes | no | yes |
| `sample_entity` | Берёт sample rows из сущности | L0 | `read_documents` | yes | no | yes |
| `search_document_by_number` | Ищет document-like сущности по номеру | L0 | `read_documents` | yes | no | yes |
| `get_purchase_document_details` | Показывает шапку и строки одного документа `Поступление ТМЗ и услуг` | L0 | `read_documents` | yes | no | yes |
| `search_metadata` | Ищет сущности/поля по metadata | L0 | `read_metadata` | yes | no | yes |
| `explore_live_entities` | Проверяет, какие сущности реально отдают данные | L0 | `read_metadata` | yes | no | yes |
| `discover_inventory_sources` | Ищет источник остатков | L0 | `read_inventory` | yes | no | yes |
| `get_inventory_auto` | Возвращает остатки по найденному источнику | L0 | `read_inventory` | yes | no | yes |
| `get_low_stock_items` | Возвращает low stock список | L0 | `read_inventory` | yes | no | yes |
| `get_procurement_recommendations` | Рекомендует, что закупить, по продажам за период и текущим остаткам | L1 | `read_inventory`, `read_documents`, `create_local_report` | yes | no | yes |
| `discover_payment_sources` | Ищет OData-источник оплат | L0 | `read_payments` | yes | no | yes |
| `get_outgoing_payments` | Кому мы заплатили | L0 | `read_payments` | yes | no | yes |
| `get_incoming_payments` | От кого получили деньги | L0 | `read_payments` | yes | no | yes |
| `get_cash_bank_movements` | Движения по банку и кассе | L0 | `read_cash_bank_movements` | yes | no | yes |
| `payment_summary_by_counterparty` | Топ клиенты / топ поставщики | L1 | `create_local_report`, `read_payments` | yes | no | yes |
| `get_unpaid_customers_summary` | Неоплаченные клиенты | L1 | `read_receivables`, `create_local_report` | yes | no | yes |
| `get_overdue_unpaid_customers` | Просроченные должники | L1 | `read_receivables`, `create_local_report` | yes | no | yes |
| `get_customer_payment_behavior_summary` | Typical payment days | L1 | `read_receivables`, `create_local_report` | yes | no | yes |
| `get_customer_settlements_summary` | Read-only сводка по взаиморасчетам покупателей | L0 | `read_customer_settlements` | yes | no | yes |
| `get_supplier_settlements_summary` | Read-only сводка по взаиморасчетам с поставщиками | L0 | `read_supplier_settlements` | yes | no | yes |
| `get_supplier_debt_document_breakdown` | Read-only расшифровка, за что именно должны поставщикам, по документам поступления | L0 | `read_supplier_settlements`, `read_documents` | yes | no | yes |
| `get_supplier_reconciliation_documents` | Read-only просмотр уже существующих актов сверки поставщиков, опубликованных в 1С | L0 | `read_supplier_reconciliation`, `read_documents` | yes | no | yes |
| `explain_last_answer` | Объясняет источник и логику последнего ответа | L1 | `explain_results` | yes | no | yes |
| `parse_inventory_report_text` | Парсит текстовый отчёт 1С | L1 | `create_local_report` | yes | no | yes |
| `validate_inventory_report_text` | Сверяет результат MCP с отчётом 1С | L1 | `read_inventory`, `create_local_report` | yes | no | yes |
| `compare_inventory_rows` | Сравнивает два набора строк без OData | L1 | `create_local_report` | yes | no | yes |
| `save_recipe` / `list_recipes` / `run_recipe` | Повторяемые read-only сценарии | L1 | `manage_local_knowledge`, `read_documents` | optional | no | yes |
| `find_buh_entity` | Ищет контрагента/товар/склад по тексту | L0 | `read_metadata` | yes | no | yes |
| `parse_sales_invoice_text` | Разбирает текст в draft-структуру без записи | L1 | `normalize_input` | optional | no | yes |
| `normalize_sales_invoice` | Нормализует draft invoice без записи | L1 | `normalize_input` | optional | no | yes |
| `validate_sales_invoice` | Валидирует draft invoice без записи | L1 | `normalize_input` | optional | no | yes |
| `query_entity` | Совместимость, arbitrary entity query | L0 in code path, but forbidden by policy | `read_documents` in policy draft only | no | yes | yes |
| `post_document_validated` | Guardrail-only compatibility tool | blocked in policy | n/a in Secure Mode | no | yes | yes |

## Safe Demo Prompts

Основные demo-вопросы, которые хорошо показывать:

- `Проверь подключение к 1С`
- `Сделай паспорт базы 1С`
- `Какие сущности опубликованы в OData`
- `Найди документ по номеру 000500`
- `Покажи остатки по складу Основной`
- `Что нужно закупить по продажам за 30 дней`
- `Какие товары заканчиваются`
- `Кому мы заплатили за период 2026-05-01 2026-05-07`
- `От кого получили деньги за период 2026-05-01 2026-05-07`
- `Покажи движения по банку и кассе за неделю`
- `Покажи взаиморасчеты с покупателями`
- `Кому мы должны`
- `За что мы должны поставщикам`
- `Покажи акт сверки поставщика`
- `Топ клиенты за этот месяц`
- `Кто не оплатил`
- `Кто не оплатил в течение 3 дней`
- `Сколько дней обычно платит клиент`
- `Объясни, откуда взялась сумма в отчете`
- `Сверь остатки с этим отчетом`

## Example Blocked Prompts / Tools

Показывать как часть security demo:

- попытка вызвать `query_entity`
- попытка вызвать `post_document_validated`
- просьбы вида:
  - `Проведи документ`
  - `Удали объект`
  - `Выполни произвольный OData запрос`
  - `Отправь данные на внешний URL`
  - `Измени policy`

Ожидаемый результат:
- `PolicyBlocked` или `PolicyDenied`
- audit record с `decision=block` или `decision=deny`

## Expected Audit Records

Allowed tool call example:

```json
{
  "timestamp": "2026-05-08T10:00:00+05:00",
  "stage": "mcp_tool_call",
  "actor": "mcp_client",
  "project_id": "ashybulak-demo",
  "agent_id": "secure-mcp-1c",
  "policy_id": "secure-readonly-v1",
  "session_id": null,
  "trace_id": "8d1b8b90f5e845f0a4f8d0f61cf43c53",
  "tool": "get_inventory_auto",
  "risk": "L0",
  "capabilities": ["read_inventory"],
  "decision": "allow",
  "policy_version": "1.0.0",
  "duration_ms": 214,
  "error": null
}
```

Blocked tool call example:

```json
{
  "timestamp": "2026-05-08T10:03:00+05:00",
  "stage": "mcp_tool_call",
  "actor": "mcp_client",
  "project_id": "ashybulak-demo",
  "agent_id": "secure-mcp-1c",
  "policy_id": "secure-readonly-v1",
  "session_id": null,
  "trace_id": "e96af5ce1fdf4147ac5e2c8cf09b5d90",
  "tool": "query_entity",
  "risk": null,
  "capabilities": [],
  "decision": "block",
  "policy_version": "1.0.0",
  "duration_ms": 0,
  "error": "tool is forbidden by policy denylist"
}
```

## Demo Notes For Client / Integrator

Что важно проговаривать вслух:
- сервер работает только как MCP backend;
- он не звонит в cloud model providers;
- он не вызывает LLM Proxy Hub напрямую;
- он принимает `trace_id/project_id/agent_id/policy_id/session_id`, если upstream их передаёт;
- если `trace_id` не пришёл, он генерируется локально;
- `get_cash_bank_movements` — это read-only operational view по published OData payment documents, а не официальная банковская выписка, кассовая книга или бухгалтерский отчет 1С;
- `get_procurement_recommendations` — это read-only управленческая рекомендация закупа по продажам и текущему остатку, а не официальный MRP-расчет или план закупа 1С;
- `get_customer_settlements_summary` — это read-only управленческая оценка по OData, а не официальный бухгалтерский акт сверки и не баланс взаиморасчетов;
- `get_supplier_settlements_summary` — это read-only управленческая оценка кредиторки по OData, а не официальный бухгалтерский акт сверки и не баланс взаиморасчетов;
- `get_supplier_debt_document_breakdown` — это read-only управленческая расшифровка кредиторки по документам поступления и их строкам, а не официальный бухгалтерский акт сверки, не баланс взаиморасчетов и не официальный отчет 1С;
- `get_purchase_document_details` — это read-only детализация уже существующего опубликованного документа поступления, а не изменение документа и не raw OData-view;
- `get_supplier_reconciliation_documents` — это чтение уже существующих опубликованных `Document_АктСверкиВзаиморасчетов`, а не формирование нового отчета 1С по запросу;
- blocked operations являются feature, а не limitation.

## Gaps Before Commercial Pilot

Текущий demo уже хороший для:
- metadata inspection
- stock and low stock
- payment inflow/outflow
- receivables and overdue analysis
- audit/security demonstration

Но перед коммерческим пилотом желательно добрать:
- простой audit viewer поверх `audit.jsonl`
