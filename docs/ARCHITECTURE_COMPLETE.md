# Полная архитектура AshybulakStroy MCP 1C Bridge

## Слои

```text
MCP Server
├── Tools: операции
├── Resources: состояние и справочники
├── Prompts: роли и режимы работы
└── BUH layer
    ├── OData: чтение
    └── RPC: действия
```

## Agent-based слой

```text
capabilities/
project_knowledge/
docs/rules/
prompts/
templates/
validation/
normalization/
```

## Safe write pipeline

```text
parse -> normalize -> validate -> review -> create -> validate_document -> post
```
