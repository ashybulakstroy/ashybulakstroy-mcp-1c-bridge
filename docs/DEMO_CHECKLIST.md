# Demo Checklist

Этот чеклист нужен перед демонстрацией `mcp-1c-bridge` как secure read-only AI bridge для 1С Казахстан.

## Pre-demo Checklist

- проект открывается из корня репозитория
- локальное окружение `.venv` существует
- `config/policy.yaml` на месте
- demo docs открываются без локальных правок
- рабочее дерево проверено через `git status`

## Environment Checklist

- Python `3.11` или `3.12`
- есть `.venv`
- переменные `ONEC_*` и `BRIDGE_*` настроены
- путь `BRIDGE_AUDIT_LOG_PATH` известен
- `audit/` доступен для записи

## 1C OData Checklist

- опубликована OData-база 1С
- используется отдельный read-only OData user
- `ONEC_ODATA_URL` указывает на published OData endpoint
- опубликованы документы/сущности, которые нужны для demo
- если показываете остатки, опубликован источник остатков
- если показываете оплаты и движения, опубликованы bank/cash payment documents

## Security Checklist

- сервер работает в `read_only`
- `SecureToolRunner` активен
- все MCP tools зарегистрированы через `@secure_tool()`
- startup policy coverage validation проходит
- forbidden tools не разрешены в `config/policy.yaml`
- audit log включён
- output filter включён
- demo не использует `query_entity` как public path
- bridge не вызывает `AshybulakStroy_chat_LLM_Proxy` напрямую
- bridge не вызывает OpenAI/Anthropic/Gemini/Groq/OpenRouter напрямую

## Command Checklist

Активировать окружение:

```powershell
cd C:\Work\Projects\Prj_9_MCP_1C_Ashybulak
.\.venv\Scripts\Activate.ps1
```

Проверить git status:

```powershell
git status
```

Прогнать тесты:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Проверить demo quality pack:

```powershell
.\.venv\Scripts\python.exe scripts\demo_health_check.py
```

Проверить audit verifier:

```powershell
.\.venv\Scripts\python.exe scripts\verify_audit_log.py
```

Запустить MCP server:

```powershell
ashybulak-1c-bridge
```

## Demo Flow

1. Показать, что сервер работает как MCP backend, а не как LLM client.
2. Показать `Secure Mode`: policy, audit, blocked operations.
3. Показать metadata/read-only diagnostics:
   `get_server_status`, `setup_wizard`, `generate_1c_database_profile`
4. Показать бизнес read-only сценарии:
   - остатки
   - поиск документа по номеру
   - взаиморасчёты
   - движения по банку/кассе
5. Показать blocked operation:
   например `query_entity`
6. После demo показать audit verification.

## Expected Successful Results

- `pytest` зелёный
- `scripts/demo_health_check.py` возвращает `OK`
- server стартует без падения startup validation
- read-only tools возвращают нормализованные данные
- audit log пополняется после tool calls
- blocked requests дают `PolicyBlocked` или `PolicyDenied`
- demo docs совпадают с policy и startup checks

## Expected Blocked Operations

- `query_entity`
- `post_document_validated`
- `Проведи документ`
- `Удалить объект`
- `Выполни произвольный OData запрос`
- `Измени policy`
- `Отключи audit log`

## Post-demo Audit Verification

1. Убедиться, что после demo появился `audit/audit.jsonl` или заданный файл audit log.
2. Прогнать verifier:

```powershell
.\.venv\Scripts\python.exe scripts\verify_audit_log.py
```

3. Проверить, что есть записи:
- `allow` для normal demo tools
- `block` или `deny` для forbidden/unknown operations
- `trace_id` присутствует в каждой записи

## Notes

- `get_customer_settlements_summary` — это read-only management estimate, а не официальный бухгалтерский акт сверки.
- `get_cash_bank_movements` — это read-only operational view, а не официальная банковская выписка или кассовая книга 1С.
