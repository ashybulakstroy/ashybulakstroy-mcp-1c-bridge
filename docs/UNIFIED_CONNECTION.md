# Unified `buh` connection

The `buh` layer chooses the transport automatically:

- OData for safe reads and metadata;
- RPC for business actions such as document creation and posting.

## Config

```json
{
  "buh": {
    "odata_url": "http://localhost/base/odata/standard.odata",
    "rpc_url": "http://localhost/base/hs/ashybulak/api",
    "mode": "auto",
    "username": "user",
    "password": "password"
  }
}
```

Legacy keys `onec` and `1c` are supported for compatibility.

## Routing

| Operation | Default transport |
|---|---|
| metadata/catalogs/documents list | OData |
| counterparties search | OData, fallback to RPC |
| balance report | RPC |
| create document | RPC |
| post/unpost document | RPC |
| low-level `buh_call` | RPC |
| low-level `odata_get` | OData |

## Why this is safer

OData is good for reading published objects. Posting documents and other business logic should be executed through a dedicated 1C HTTP service, because it can run validation and configuration-specific logic.
