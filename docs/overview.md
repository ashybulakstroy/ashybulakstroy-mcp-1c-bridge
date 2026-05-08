# Overview

AshybulakStroy MCP 1C Bridge — слой между 1С и AI-клиентом, который делает OData-публикацию 1С пригодной для безопасной работы через MCP.

Важно:
- это MCP backend, а не LLM client;
- runtime не вызывает `AshybulakStroy_chat_LLM_Proxy` напрямую;
- LLM Proxy Hub должен находиться upstream и передавать в bridge correlation metadata:
  `trace_id`, `project_id`, `agent_id`, `policy_id`, `session_id`.

Текущий runtime ориентирован на четыре сценария:
- диагностика подключения и опубликованных OData-сущностей;
- поиск и чтение источников остатков;
- эвристическое получение остатков и низких остатков;
- денежные управленческие отчёты по оплатам, должникам и срокам оплаты клиентов;
- сверка MCP-результата с официальным отчётом 1С.

Дополнительно в проект уже встроены:
- capability registry;
- MCP resources и prompts;
- нормализация черновиков документов;
- validation guardrails перед потенциальной записью в 1С.

Но фактическая запись в 1С по умолчанию не выполняется: сервер остаётся read-only runtime с подготовленным каркасом под будущий RPC adapter.

Для demo-режима см.:
- [DEMO_READONLY_SECURE_MODE.md](C:/Work/Projects/Prj_9_MCP_1C_Ashybulak/docs/DEMO_READONLY_SECURE_MODE.md)
- [DEMO_PROMPTS.md](C:/Work/Projects/Prj_9_MCP_1C_Ashybulak/docs/DEMO_PROMPTS.md)
