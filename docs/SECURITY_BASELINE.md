# Security Baseline

Этот документ фиксирует текущую security baseline для `mcp-1c-bridge`.

## SecureToolRunner

`SecureToolRunner` является runtime enforcement layer для MCP tools.

Что он делает:
- загружает `config/policy.yaml`
- принимает correlation metadata
- выполняет allow/deny/block decision
- запускает tool только если decision = allow
- применяет output filter
- пишет append-only audit record

## secure_tool Decorator

Все MCP tools должны регистрироваться через `@secure_tool()`, а не через прямой `@mcp.tool()`.

Это даёт:
- обязательный route через `SecureToolRunner`
- единый registration pattern
- совместимость со startup policy validation

## Startup Policy Coverage Validation

На startup сервер проверяет:
- все зарегистрированные MCP tools перечислены в runtime registry
- каждый tool покрыт `config/policy.yaml`
- у каждого allowed tool есть `risk`
- у каждого allowed tool есть `capabilities`
- forbidden tool не может быть одновременно allowed

При ошибке startup должен завершиться с `RuntimeError`.

## Policy File

Основной policy file:

```text
config/policy.yaml
```

Он задаёт:
- `mode`
- tool allowlist
- risk level per tool
- capabilities per tool
- forbidden denylist
- output filter settings

## Risk Levels

- `L0` — safe read-only inspection and business reads
- `L1` — local analytics/explain/report without write
- `L2` — sensitive operations, denied in `read_only`
- `L3` — critical operations, always blocked
- `L4` — destructive operations, always blocked

## Capabilities

Policy capabilities отделяют intent доступа от конкретных tool names.

Примеры:
- `read_metadata`
- `read_inventory`
- `read_payments`
- `read_receivables`
- `read_documents`
- `read_customer_settlements`
- `read_cash_bank_movements`
- `create_local_report`

## Forbidden Tools

Ключевые forbidden operations:
- `query_entity`
- `raw_odata`
- `execute_1c_code`
- `direct_sql`
- `delete_object`
- `post_document`
- `unpost_document`
- `change_posted_document`
- `change_closed_period`
- `external_http`
- `disable_audit`
- `modify_policy`
- `post_document_validated`

## Audit Log

Audit log append-only:

```text
audit/audit.jsonl
```

Каждый MCP tool call должен писать audit record.

Минимальные поля:
- `timestamp`
- `trace_id`
- `actor`
- `tool`
- `risk`
- `capabilities`
- `decision`
- `policy_version`
- `duration_ms`

## Output Filter

Output filter применяется перед возвратом MCP response.

Поддерживается:
- `max_rows`
- masking IIN/BIN
- masking bank accounts
- credential redaction
- blocking external URLs in payload-like fields

## Correlation Metadata

Поддерживаются поля:
- `trace_id`
- `project_id`
- `agent_id`
- `policy_id`
- `session_id`

Если `trace_id` не пришёл, сервер генерирует его локально.

## Why MCP Bridge Does Not Call LLM Proxy Directly

`mcp-1c-bridge` должен оставаться MCP backend, а не LLM client.

Поэтому:
- он не вызывает `AshybulakStroy_chat_LLM_Proxy` по HTTP
- он не вызывает cloud model providers напрямую
- он только принимает correlation metadata от upstream components

Ожидаемая схема:

```text
LLM Proxy Hub (upstream)
  -> MCP client call
  -> mcp-1c-bridge
  -> SecureToolRunner
  -> 1C adapter/OData
```

Current actual flow:

```text
Open Interpreter / MCP client
  -> direct MCP call to mcp-1c-bridge
  -> SecureToolRunner
  -> policy decision
  -> output filter
  -> audit log
  -> 1C adapter / OData
```

Future intended flow:

```text
User query
  -> AshybulakStroy_chat_LLM_Proxy
  -> model/provider decision
  -> MCP call with trace_id/project_id/agent_id/policy_id/session_id
  -> mcp-1c-bridge
  -> SecureToolRunner
  -> 1C adapter / OData
  -> output filter
  -> audit log linked by trace_id
  -> final answer
```

## Known Remaining Risks

- enforcement сосредоточен в одном MCP runtime и не защищает от появления второго независимого сервера вне этого контура
- read-only business summaries по OData могут быть управленческими оценками, а не официальными бухгалтерскими отчётами
- качество safe business demo зависит от того, какие сущности реально опубликованы в OData
- audit verifier проверяет структуру записей, но не заменяет ручной review demo traces
