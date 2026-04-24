# Architecture

```text
1С:Бухгалтерия для Казахстана 3.0
        │ OData
        ▼
OneCODataClient
        │
Discovery + Inventory Heuristics
        │
KnowledgeStore / SQLite Recipes
        │
MCP Tools
        │
AI Client
        │
User
```

## Components

- `core_server.py` — MCP tools and entrypoint.
- `odata.py` — OData client, metadata discovery, inventory source detection.
- `knowledge.py` — recipe memory in SQLite.
- `validation.py` — report text parser and reconciliation.
- `config.py` — environment settings.
