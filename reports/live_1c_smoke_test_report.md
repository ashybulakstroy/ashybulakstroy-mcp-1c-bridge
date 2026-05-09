# Live 1C Smoke Test Report

- Generated: `2026-05-09T16:16:07.769199+05:00`
- Base URL: `http://192.168.1.183/SaryDala`
- Service URL: `http://192.168.1.183/SaryDala/odata/standard.odata`
- Entity sets discovered in metadata: `1192`

| Check | Status | Details |
|---|---|---|
| `config` | `OK` | service_url=http://192.168.1.183/SaryDala/odata/standard.odata |
| `auth_env` | `OK` | username/password are configured in environment |
| `base_url_reachable` | `OK` | HTTP 301 |
| `metadata_reachable` | `OK` | HTTP 200, bytes=4153448 |
| `authentication` | `OK` | metadata authenticated successfully |
| `odata_metadata_has_entity_sets` | `OK` | entity_sets=1192 |
| `write_operations` | `OK` | Smoke test performs GET/read-only metadata access only. |
