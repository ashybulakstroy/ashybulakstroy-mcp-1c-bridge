# ROADMAP: Secure AI Bridge for 1C Kazakhstan

## 0. Product Strategy

Main strategic direction:

```text
Do not start as a standalone firewall product.
Start as Secure Mode inside `ashybulakstroy-mcp-1c-bridge`.
Use `AshybulakStroy_chat_LLM_Proxy` as LLM infrastructure.
Extract `agent-firewall-core` later as reusable security engine.
```

Public market offer:

```text
Secure AI access to 1C:Accounting Kazakhstan through MCP,
with read-only mode, audit log, policy firewall, and controlled tools.
```

Core principle:

```text
Self-development is allowed.
Self-permission is forbidden.
```

The agent may create new tool candidates, but it must not be able to grant itself production permissions, bypass policies, access 1C OData directly, or send data to external networks.

---

# 1. Target Repository Strategy

## 1.1. Main commercial product

Repository:

```text
ashybulakstroy-mcp-1c-bridge
```

Role:

```text
Main product for 1C users.
Contains MCP tools for 1C:Accounting Kazakhstan.
Includes Secure Mode / Agent Firewall integration.
```

## 1.2. LLM infrastructure

Repository:

```text
AshybulakStroy_chat_LLM_Proxy
```

Role:

```text
Controls LLM provider access, routing, limits, logging, masking, and project-level governance.
```

## 1.3. New reusable security module

Future repository:

```text
ashybulakstroy-agent-firewall-core
```

Role:

```text
Reusable policy engine, risk scorer, capability checker, audit decision engine, output filter, and static analyzer.
```

Do not market this separately at the beginning. Use it internally inside the 1C product first.

---

# 2. Phase 0 — Product Packaging

## Goal

Prepare product positioning that is understandable to business owners, accountants, and IT specialists.

## Main message

```text
AI can work with 1C, but it cannot damage accounting data.
```

## Tasks

- Update README of `ashybulakstroy-mcp-1c-bridge`.
- Add architecture diagram.
- Add safe-mode explanation.
- Add risk model explanation.
- Add first use cases.
- Add installation/demo section.
- Add limitations and security guarantees.

## First use cases

```text
Ask 1C in natural language.
Find customer debts.
Show stock balances.
Explain document movements.
Reconcile reports.
Find accounting inconsistencies.
Generate management reports.
```

## Deliverables

- Product README.
- Architecture diagram.
- Demo script.
- Security model document.
- Initial use-case list.

## Acceptance criteria

- A non-technical business user can understand what the product does.
- An IT/security user can understand why it is safe.
- The product is positioned as secure AI access to 1C, not as a generic chatbot.

---

# 3. Phase 1 — Read-only Secure MVP

## Goal

Create a safe MVP that can be demonstrated to clients and 1C integrators.

## Repository

```text
ashybulakstroy-mcp-1c-bridge
```

## Required mode

```text
Read-only mode.
No write operations to 1C.
No posting documents.
No deleting objects.
No raw OData tool.
No execute_1c_code tool.
```

## MCP tools to implement

```text
get_counterparty
search_counterparties
get_invoice
search_invoices
get_stock_balance
get_mutual_settlements
get_cash_bank_movements
create_local_report
explain_document_movements
```

## Security tasks

- Add `policy.yaml`.
- Add tool allowlist.
- Add tool risk levels.
- Add audit log.
- Add output row limit.
- Add optional PII masking.
- Deny dangerous tools.
- Deny raw OData access.
- Deny arbitrary 1C code execution.
- Deny direct SQL access.

## Example `policy.yaml`

```yaml
mode: read_only

tools:
  get_counterparty:
    risk: L0
    capabilities:
      - read_counterparties
    auto_approval: true

  search_counterparties:
    risk: L0
    capabilities:
      - read_counterparties
    auto_approval: true

  get_invoice:
    risk: L0
    capabilities:
      - read_invoices
    auto_approval: true

  search_invoices:
    risk: L0
    capabilities:
      - read_invoices
    auto_approval: true

  get_stock_balance:
    risk: L0
    capabilities:
      - read_stock_balance
    auto_approval: true

  get_mutual_settlements:
    risk: L0
    capabilities:
      - read_mutual_settlements
    auto_approval: true

  create_local_report:
    risk: L1
    capabilities:
      - create_local_report
    auto_approval: true

forbidden:
  - raw_odata
  - execute_1c_code
  - direct_sql
  - delete_object
  - post_document
  - unpost_document
  - change_posted_document
  - change_closed_period
  - external_http
  - send_email
  - upload_file
  - disable_audit
  - modify_policy
```

## Acceptance criteria

- Agent can answer questions using 1C data.
- Agent cannot modify 1C data.
- All tool calls are logged.
- Every tool has risk level and capabilities.
- Output is limited by row count.
- Dangerous commands are blocked.
- Raw OData access is technically unavailable to the agent.

---

# 4. Phase 2 — Audit Dashboard and Trust Layer

## Goal

Make system activity visible and explainable for clients.

## Repository

```text
ashybulakstroy-mcp-1c-bridge
```

or later:

```text
separate small web dashboard
```

## Features

```text
View all user requests.
View all tool calls.
View actor/agent.
View tool name.
View capabilities used.
View allow/deny/block decision.
View execution time.
View errors.
View risk level.
Filter by date/tool/risk/decision.
```

## Minimal audit log structure

```json
{
  "timestamp": "2026-05-07T15:00:00+05:00",
  "actor": "open_interpreter",
  "user_query": "Покажи долги контрагентов",
  "tool": "get_mutual_settlements",
  "risk": "L0",
  "capabilities": ["read_mutual_settlements"],
  "decision": "allow",
  "rows_returned": 25,
  "policy_version": "1.0.0",
  "duration_ms": 320,
  "error": null
}
```

## Acceptance criteria

- Audit log exists.
- Audit records are append-only from the agent point of view.
- There is a way to inspect logs.
- There are filters by risk/tool/date/decision.
- Denied and blocked events are recorded.
- Every AI answer can be traced back to MCP tool calls.

---

# 5. Phase 3 — Link with LLM Proxy Hub

## Goal

Add infrastructure control over LLM calls.

## Repository

```text
AshybulakStroy_chat_LLM_Proxy
```

## Features to add

```text
project_id
agent_id
policy_id
risk-aware routing
prompt logging controls
PII masking before provider
rate limits per project
token limits per agent
provider allowlist
shared trace_id with MCP Gateway
```

## Risk-aware routing example

```yaml
routing:
  L0:
    provider: local_or_low_cost
  L1:
    provider: gpt_compatible
  L2:
    provider: approved_secure_provider
  L3:
    action: block_or_queue
  L4:
    action: block
```

## Required traceability

Every request should be traceable:

```text
user query
  -> LLM proxy request
  -> model/provider decision
  -> MCP tool call
  -> 1C Adapter call
  -> final answer
```

## Acceptance criteria

- LLM Proxy understands `project_id`.
- LLM Proxy understands `agent_id`.
- LLM Proxy records or forwards `trace_id`.
- MCP Gateway and LLM Proxy logs can be correlated.
- Token and rate limits exist per project/agent.
- PII masking before cloud model calls is available.
- Provider allowlist exists.

---

# 6. Phase 4 — Extract Agent Firewall Core

## Goal

Move security decision logic into a reusable module.

## New repository

```text
ashybulakstroy-agent-firewall-core
```

## Components to extract

```text
policy loader
risk scorer
capability checker
tool allowlist engine
denylist engine
output filter
audit decision model
schema validation helpers
static tool analyzer
policy test helpers
```

## Usage

Initially use this module inside:

```text
ashybulakstroy-mcp-1c-bridge
```

Later it can also be used inside:

```text
AshybulakStroy_chat_LLM_Proxy
other MCP servers
other business-system adapters
```

## Do not market separately yet

Public positioning at this stage:

```text
Powered by AshybulakStroy Agent Firewall
```

## Acceptance criteria

- `mcp-1c-bridge` uses `agent-firewall-core`.
- Policy logic is no longer duplicated.
- `policy.yaml` is parsed by the shared module.
- Risk/capability checks are covered by unit tests.
- Deny decisions are explainable.
- Security behavior is deterministic.

---

# 7. Phase 5 — Limited Write Drafts

## Goal

Move carefully from read-only to safe limited write operations.

## Repository

```text
ashybulakstroy-mcp-1c-bridge
```

## New tools

```text
validate_invoice
create_invoice_draft
cancel_invoice_draft
create_counterparty_draft
request_post_invoice
```

## Important rule

Only drafts are allowed.

Forbidden:

```text
posting documents
deleting objects
changing posted documents
changing closed periods
direct register writes
raw OData writes
```

## Example policy

```yaml
tools:
  validate_invoice:
    risk: L1
    auto_approval: true
    capabilities:
      - validate_invoice

  create_invoice_draft:
    risk: L2
    auto_approval: true
    capabilities:
      - create_invoice_draft
    limits:
      max_amount: 50000
      max_items: 20
      period_must_be_open: true
      existing_counterparty_required: true
      posted_document_write: false
      audit_required: true

  cancel_invoice_draft:
    risk: L2
    auto_approval: true
    capabilities:
      - cancel_invoice_draft
    limits:
      only_draft_documents: true
      audit_required: true

  request_post_invoice:
    risk: L3
    auto_approval: false
    action: queue_only
```

## Acceptance criteria

- Agent can create invoice drafts within limits.
- Agent cannot post documents automatically.
- Agent cannot modify posted documents.
- Agent cannot change closed periods.
- Amount and item limits are enforced.
- All draft operations are logged.
- L3 operations are converted to approval requests, not executed.

---

# 8. Phase 6 — Approval Queue

## Goal

Create a safe bridge between autonomy and real accounting actions.

## Features

```text
approval queue
approval screen
document summary
change diff
actor/tool/risk display
approve/reject action
approval audit trail
```

## Flow

```text
Agent creates draft
  -> request_post_invoice
  -> Approval Queue
  -> accountant reviews
  -> approve/reject
  -> 1C Adapter posts document only after approval
```

## Acceptance criteria

- L3 operations are never executed automatically.
- There is an approval queue.
- Each queued operation has a clear summary.
- Each queued operation has actor/tool/risk metadata.
- Approval and rejection decisions are logged.
- Human-approved action is traceable to original agent request.

---

# 9. Phase 7 — Dynamic Tool Creation in Safe Mode

## Goal

Allow Open Interpreter to create new tools automatically without self-permission.

## Repositories

```text
ashybulakstroy-mcp-1c-bridge
ashybulakstroy-agent-firewall-core
```

## Required components

```text
/tools/draft
Tool Registry
Auto Policy Checker
Auto Test Runner
Risk Scorer
Capability Approval
Static Analyzer
```

## Tool lifecycle

```text
draft
  -> policy_check
  -> tests
  -> risk_scoring
  -> sandbox
  -> approved or blocked
```

## Flow

```text
Open Interpreter creates draft tool
  -> Tool Registry records it as draft
  -> Auto Policy Checker analyzes code
  -> Auto Test Runner runs tests
  -> Risk Scorer assigns L0-L4
  -> capabilities are approved or denied
  -> tool becomes approved/sandbox/blocked
```

## Auto-approval rules

Can auto-approve:

```text
L0 read-only tools
L1 report/local-analysis tools
```

Can conditionally auto-approve:

```text
L2 draft-write tools only with strict limits
```

Must never auto-approve:

```text
L3 critical accounting operations
L4 forbidden operations
```

## Static analyzer must block

```text
requests
httpx
urllib
socket
subprocess
os.system
exec
eval
raw OData URLs
direct SQL
SMTP
Telegram
webhooks
credentials in code
policy modification
registry modification
audit disabling
```

## Acceptance criteria

- Draft tool cannot execute as production tool.
- Tool with external HTTP is blocked.
- Tool with raw OData is blocked.
- Tool with exec/eval/subprocess is blocked.
- Tool without tests cannot be approved.
- Tool cannot request forbidden capability.
- Tool cannot approve itself.
- Tool cannot change policies.
- Tool cannot change audit logs.
- Tool cannot access 1C credentials.

---

# 10. Phase 8 — Commercial Pilot

## Goal

Find first users and validate market demand.

## Target customers

```text
1C franchisees
accounting outsourcing companies
small and medium businesses using 1C
construction companies
trade companies
companies with many accounting documents
```

## Pilot offer

```text
In 1-2 weeks we connect read-only AI to your 1C.
AI answers questions about stock, payments, debtors, and documents.
Data is not changed.
All actions are logged.
```

## Metrics to collect

```text
number of questions per day
most requested reports
time saved
errors found
user fears/objections
requested write operations
willingness to pay
integration complexity
```

## Suggested packages

### Demo

```text
read-only
limited number of tools
test database or demo environment
```

### Professional

```text
read-only production
audit log
report tools
LLM proxy integration
```

### Business

```text
limited drafts
approval queue
policy customization
role-based access
```

### Enterprise

```text
custom policies
on-prem deployment
advanced audit
multiple 1C databases
support SLA
```

## Acceptance criteria

- At least 3-5 pilot conversations with potential users/integrators.
- At least 1 live demo.
- Clear list of top 10 requested use cases.
- Clear list of top objections.
- Decision whether to continue read-only, add drafts, or focus on reports.

---

# 11. Phase 9 — Kazakhstan Verticalization

## Goal

Make the product specifically valuable for Kazakhstan accounting, not just generic 1C access.

## Features to develop

```text
VAT-related reports
ЭСФ-related workflows
counterparty reconciliation
tax period checks
IIN/BIN format validation
acts of reconciliation
accounts receivable
accounts payable
cash and bank movement analysis
payroll documents later and with caution
```

## Differentiation

```text
AI for 1C Kazakhstan, not just a generic chatbot.
```

## Acceptance criteria

- Product supports Kazakhstan-specific accounting terminology.
- Product includes use cases recognizable by Kazakhstani accountants.
- Product documentation mentions 1C:Бухгалтерия для Казахстана 3.0.
- Product demos use Kazakhstan-specific examples.

---

# 12. Phase 10 — Standalone Agent Firewall Product

## When to start this phase

Only after market asks questions like:

```text
Can this protect not only 1C?
Can this work with another MCP server?
Can this protect CRM/ERP/SQL?
Can we buy only the policy gateway?
```

## Product name

```text
AshybulakStroy Agent Firewall
```

## Features

```text
MCP tool governance
capability registry
policy engine
audit log
risk scoring
output filtering
network action control
dynamic tool approval
```

## Important note

Do not start here.

First prove value in the 1C vertical.

---

# 13. 90-Day Execution Plan

## Weeks 1-2

Tasks:

```text
Finalize positioning.
Update README in mcp-1c-bridge.
Add policy.yaml.
Add risk levels.
Add audit log.
Add initial architecture diagram.
```

Expected result:

```text
The product has a clear Secure Mode concept.
```

## Weeks 3-4

Tasks:

```text
Add read-only MCP tools.
Add output limits.
Deny raw OData.
Deny dangerous tools.
Prepare demo scripts.
Prepare demo/test 1C connection scenario.
```

Expected result:

```text
Working read-only demo.
```

## Weeks 5-6

Tasks:

```text
Connect with LLM Proxy Hub.
Add project_id and agent_id.
Add shared trace_id.
Add basic PII masking.
Add rate/token limits.
```

Expected result:

```text
LLM calls and MCP calls can be traced together.
```

## Weeks 7-8

Tasks:

```text
Create simple audit dashboard or log viewer.
Prepare demo for 1C integrators.
Prepare commercial pilot description.
Collect first feedback.
```

Expected result:

```text
Pilot-ready product.
```

## Weeks 9-10

Tasks:

```text
Create agent-firewall-core repository.
Move policy decision logic.
Add unit tests for policy decisions.
Add reusable output filter.
Add reusable risk scorer.
```

Expected result:

```text
Reusable firewall core exists and is used by mcp-1c-bridge.
```

## Weeks 11-12

Tasks:

```text
Start limited draft tools.
Implement validate_invoice.
Implement create_invoice_draft.
Implement request_post_invoice.
Prototype approval queue.
```

Expected result:

```text
Safe draft workflow prototype.
```

---

# 14. Immediate Next Steps for Codex Agent

Start with these tasks in order:

## Task 1 — Inspect repository

```text
Open repository: ashybulakstroy-mcp-1c-bridge
Identify current MCP tools.
Identify current OData access layer.
Identify config structure.
Identify logging structure.
```

## Task 2 — Add policy model

Create:

```text
policy.yaml
src/security/policy_loader.*
src/security/models.*
src/security/decision_engine.*
```

Required entities:

```text
ToolPolicy
RiskLevel
Capability
PolicyDecision
AllowDecision
DenyDecision
BlockDecision
```

## Task 3 — Add risk/capability enforcement

Every MCP tool call must pass through:

```text
policy_loader
capability_checker
risk_checker
decision_logger
```

Do not allow direct tool execution without policy check.

## Task 4 — Add audit log

Create append-only audit logging.

Minimum fields:

```text
timestamp
actor
tool
risk
capabilities
decision
policy_version
duration_ms
error
```

## Task 5 — Add default read-only policy

Default mode:

```text
read_only
```

Allowed risk:

```text
L0
L1
```

Blocked:

```text
L2 write unless explicitly enabled
L3
L4
```

## Task 6 — Add forbidden tool denylist

Block any tool or code path matching:

```text
raw_odata
execute_1c_code
direct_sql
delete_object
post_document
unpost_document
change_posted_document
external_http
send_email
upload_file
disable_audit
modify_policy
```

## Task 7 — Add output filter

Implement:

```text
max rows
optional IIN/BIN masking
optional bank account masking
credential detection
external URL warning/blocking
```

## Task 8 — Add tests

Add tests for:

```text
allowed read-only tool
blocked raw OData tool
blocked external HTTP tool
blocked L3 tool
audit log created
output row limit applied
capability denied
```

## Task 9 — Update README

Add sections:

```text
Secure Mode
Risk levels
Capabilities
Policy file
Audit log
Read-only MVP
Forbidden operations
Architecture
```

## Task 10 — Prepare demo

Create demo prompts:

```text
Покажи остатки по складу.
Найди долги покупателей.
Покажи движение по документу.
Сформируй отчет по оплатам.
Объясни, откуда взялась сумма в отчете.
```

---

# 15. Final Strategic Rule

Build in this order:

```text
Trust
  -> Usefulness
  -> Control
  -> Safe Action
  -> Self-development
  -> Platform
```

Do not start with full autonomy.

Start with:

```text
Working demo:
AI asks 1C, answers using real data, but technically cannot change the database.
```
