# Live Testing: SaryDala

## Environment Variables

Current project canonical names:

```env
ONEC_ODATA_URL=http://192.168.1.183/SaryDala/odata/standard.odata
ONEC_USERNAME=<local-only>
ONEC_PASSWORD=<local-only>
```

Also supported by live testing scripts as aliases:

```env
ONEC_ODATA_BASE_URL=http://192.168.1.183/SaryDala
ONEC_ODATA_USERNAME=<local-only>
ONEC_ODATA_PASSWORD=<local-only>
```

Не коммитьте `.env`, `.env.local` или реальные secrets.

## Run Smoke Test

```powershell
.\.venv\Scripts\python.exe scripts\live_1c_smoke_test.py
```

## Run Schema Discovery

```powershell
.\.venv\Scripts\python.exe scripts\discover_1c_odata_schema.py
```

## Run Live MCP Tool Matrix

```powershell
.\.venv\Scripts\python.exe scripts\live_mcp_tool_matrix_test.py
```

## Interpret Reports

- smoke report: `reports/live_1c_smoke_test_report.md`
- schema report: `reports/1c_schema_discovery_report.md`
- tool matrix:
  - `reports/live_mcp_tool_matrix_report.md`
  - `reports/live_mcp_tool_matrix_report.json`
- generated schema knowledge base:
  - `docs/generated/1C_ODATA_SCHEMA_SARYDALA.md`
  - `docs/generated/1C_ODATA_SCHEMA_SARYDALA.json`

## If Entity Sources Are Missing

- first inspect `docs/generated/1C_ODATA_SCHEMA_SARYDALA.md`
- check `has_data=true/false` in candidate sections, not only the entity names
- check whether the expected document/register is published in OData
- if metadata exists but row reads return `401`, treat that entity as restricted
- if no reliable source exists, tool should return `PASS_EMPTY` or a clear missing-source message, not fabricate balances
- for the current `SaryDala` test base, payment/bank/cash metadata is visible, but published top-level movement documents may still contain zero readable rows
