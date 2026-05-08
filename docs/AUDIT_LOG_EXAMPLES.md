# Audit Log Examples

Этот документ показывает, как выглядят audit records в Secure Mode.

Не используйте в примерах реальные логины, пароли или реальные данные компании.

## Required Audit Fields

Каждая запись должна включать:
- `timestamp`
- `trace_id`
- `actor`
- `tool`
- `risk`
- `capabilities`
- `decision`
- `policy_version`
- `duration_ms`

Дополнительно обычно присутствуют:
- `project_id`
- `agent_id`
- `policy_id`
- `session_id`
- `error`

## Allowed Tool Call Example

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
  "tool": "get_cash_bank_movements",
  "risk": "L0",
  "capabilities": ["read_cash_bank_movements"],
  "decision": "allow",
  "policy_version": "1.0.0",
  "duration_ms": 182,
  "error": null
}
```

## Blocked Tool Call Example

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

## Denied Unknown Tool Example

Если в runtime поступит tool call, которого нет в allowlist и он не в forbidden denylist, ожидается `deny`:

```json
{
  "timestamp": "2026-05-08T10:05:00+05:00",
  "stage": "mcp_tool_call",
  "actor": "mcp_client",
  "project_id": "ashybulak-demo",
  "agent_id": "secure-mcp-1c",
  "policy_id": "secure-readonly-v1",
  "session_id": null,
  "trace_id": "2a4d54a8db814fd19413bcb4b6f1e7c7",
  "tool": "unknown_tool",
  "risk": null,
  "capabilities": [],
  "decision": "deny",
  "policy_version": "1.0.0",
  "duration_ms": 0,
  "error": "tool is not present in the policy allowlist"
}
```

## How To Run Audit Verifier

```powershell
cd C:\Work\Projects\Prj_9_MCP_1C_Ashybulak
.\.venv\Scripts\python.exe scripts\verify_audit_log.py
```

С указанием файла:

```powershell
.\.venv\Scripts\python.exe scripts\verify_audit_log.py audit\audit.jsonl
```

## How To Interpret Audit Records

- `decision=allow` — tool был разрешён policy и выполнен
- `decision=block` — tool попал под hard block
- `decision=deny` — tool не прошёл allowlist/risk/mode checks
- `trace_id` — связывает вызов с upstream request
- `duration_ms` — полезен для demo troubleshooting и profiling
- `error` — должен быть пустым для normal allowed flow
- `risk` и `capabilities` показывают, почему tool вообще мог быть исполнен
- `policy_version` помогает доказать, какая именно policy действовала во время demo

## Practical Demo Reading

Во время demo полезно показать:
- одну `allow` запись
- одну `block` запись
- что `trace_id` и `tool` видны сразу
- что audit существует даже для запрещённых операций
