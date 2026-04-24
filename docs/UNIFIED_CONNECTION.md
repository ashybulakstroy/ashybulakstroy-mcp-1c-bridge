# Unified `buh` connection

The repository contains a `buh` layer that conceptually separates safe reads from business actions:

- OData for safe reads and metadata;
- RPC for business actions such as document creation and posting.

## Config

```json
{
  "ONEC_ODATA_URL": "http://localhost/base/odata/standard.odata",
  "ONEC_USERNAME": "user",
  "ONEC_PASSWORD": "password",
  "ONEC_TIMEOUT_SECONDS": 60,
  "ONEC_VERIFY_SSL": true,
  "BRIDGE_DB_PATH": "./bridge_knowledge.sqlite3",
  "BRIDGE_MAX_TOP": 500
}
```

These values are loaded from `.env` in the current runtime.

## Routing

| Operation | Default transport |
|---|---|
| metadata inspection | OData |
| inventory source detection | OData |
| inventory reading | OData |
| report reconciliation | local comparison after OData read |
| future create/post operations | RPC or HTTP service on 1C side |

## Why this is safer

OData is suitable for published read-only objects. Posting documents and other business logic should be delegated to a dedicated 1C HTTP or RPC layer, because it can enforce configuration-specific validation and permissions.
