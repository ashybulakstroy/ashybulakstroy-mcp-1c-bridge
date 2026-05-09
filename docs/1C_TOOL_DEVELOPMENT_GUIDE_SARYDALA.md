# 1C Tool Development Guide: SaryDala

Этот документ нужен будущим Codex agents и разработчикам, которые будут добавлять новые read-only tools под реальную публикацию `SaryDala`.

## How To Read Generated Schema Docs

- основной Markdown обзор: [docs/generated/1C_ODATA_SCHEMA_SARYDALA.md](docs/generated/1C_ODATA_SCHEMA_SARYDALA.md)
- полная машиночитаемая схема: [docs/generated/1C_ODATA_SCHEMA_SARYDALA.json](docs/generated/1C_ODATA_SCHEMA_SARYDALA.json)
- сначала смотрите candidate sections, потом уже полную category map

## Which Entities Are Safe And Useful

- `Document_*` обычно безопаснее для document search и movement views, чем technical catalogs
- `AccumulationRegister_*_RecordType` часто полезнее для inventory и settlement-style reads, чем parent set without row detail
- `Catalog_Контрагенты`, `Catalog_БанковскиеСчета`, `Catalog_Номенклатура` полезны для lookup, но не должны автоматически считаться business transaction sources

## Which Entities Are Missing Or Unreliable

- attachment-like and technical entities:
  - `*ПрисоединенныеФайлы*`
  - `*Удалить*`
  - `*ЭлектронныеПодписи*`
  - `*Сертификаты*`
- entities that return `401` on row reads despite visible metadata must be treated as restricted
- payment and settlement heuristics must not assume that a “bank” or “counterparty” term alone means a movement source

## Recommended Fields

- document number search:
  - `Number`
  - `Номер`
- dates:
  - `Date`
  - `Дата`
  - `Period`
  - `Период`
- amounts:
  - `СуммаДокумента`
  - `Сумма`
  - `Amount`
- counterparties:
  - `Контрагент`
  - `Контрагент_Key`
  - `ДоговорКонтрагента_Key`
- warehouse:
  - `Склад`
  - `Склад_Key`
  - `СтруктурноеПодразделение_Key`
- bank/cash movements:
  - bank docs: prefer payment/settlement documents, not bank account catalogs
  - cash docs: `ПриходныйКассовыйОрдер`, `РасходныйКассовыйОрдер`
- inventory:
  - prefer accumulation register row types with item + quantity + warehouse
- payments:
  - prefer documents with clear direction, amount, date, counterparty
- customer settlements:
  - prefer settlement-like registers or sales+payment summary fallback

## Known Naming Patterns In This Publication

- `Document_*` for main business documents
- `Document_*_<tabular section>` for tabular sections
- `AccumulationRegister_*_RecordType` often exposes the usable row structure
- `InformationRegister_*` may be useful for reference facts, but many are technical
- some technical entities contain business words and must be filtered out by score penalties

## Safe OData Filter Construction Rules

- always escape string literals before `$filter`
- use date pushdown when date fields are known
- prefer exact or substring filters on known fields only
- never expose arbitrary `$filter` construction to the agent

## Escaping And Sanitizing Rules

- escape single quotes in OData string literals as doubled quotes
- validate `movement_type`, `account_type`, `direction` through allowlists
- validate dates as `YYYY-MM-DD`
- validate numeric thresholds through explicit decimal parsing

## Performance Rules

- always cap `limit`
- always date-filter when possible
- avoid unbounded scans
- push filters down to OData
- use metadata discovery first, then read rows only from the best candidates

## Security Rules

- no raw OData exposed to the agent
- no credentials in logs or generated docs
- no write operations
- no internal URLs in tool output
- all tools must remain behind `SecureToolRunner`

## Checklist For A New Read-only Tool

- register through `@secure_tool()`
- add tool entry in `config/policy.yaml`
- choose `L0` or `L1`
- declare capability
- add unit tests
- ensure audit record is created
- ensure output filter applies
- update docs
- add a live test case against SaryDala
