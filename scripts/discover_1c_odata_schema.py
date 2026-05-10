from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ashybulakstroy_mcp_1c_bridge.config import load_settings
from ashybulakstroy_mcp_1c_bridge.odata import EntityInfo, OneCODataClient

from live_1c_common import configure_quiet_logging, now_iso, prepare_live_env, repo_root, write_json, write_markdown


def category_for_entity(entity: EntityInfo) -> str:
    name = entity.name.lower()
    etype = (entity.entity_type or "").lower()
    haystack = f"{name} {etype}"
    if "catalog_" in name or "catalog" in haystack or "справочник" in haystack:
        return "Catalogs"
    if "document_" in name or "document" in haystack or "документ" in haystack:
        return "Documents"
    if "accumulationregister" in haystack or "informationregister" in haystack or "register" in haystack or "регистр" in haystack:
        return "Registers"
    return "Other entities"


def serialize_entity(client: OneCODataClient, entity: EntityInfo) -> dict[str, Any]:
    field_names = [field.name for field in (entity.fields or [])]
    payment_map = client._map_payment_fields(field_names)
    sales_map = client._map_sales_fields(field_names)
    inventory_map = client._map_inventory_fields(field_names)
    document_map = client._map_document_fields(field_names)
    return {
        "entity_set": entity.name,
        "entity_type": entity.entity_type,
        "fields": [
            {"name": field.name, "type": field.type, "nullable": field.nullable}
            for field in (entity.fields or [])
        ],
        "possible_date_field": payment_map.get("date") or sales_map.get("date") or inventory_map.get("period") or document_map.get("date"),
        "possible_number_field": payment_map.get("number") or sales_map.get("number") or document_map.get("number"),
        "possible_amount_fields": [x for x in {payment_map.get("amount"), sales_map.get("amount"), inventory_map.get("amount"), document_map.get("amount")} if x],
        "possible_counterparty_fields": [x for x in {payment_map.get("counterparty"), sales_map.get("counterparty"), document_map.get("counterparty")} if x],
        "possible_warehouse_fields": [x for x in {inventory_map.get("warehouse")} if x],
        "possible_currency_fields": [x for x in {payment_map.get("currency")} if x],
        "comments_for_tool_developers": build_comments(entity, payment_map, sales_map, inventory_map, document_map),
    }


def build_comments(entity: EntityInfo, payment_map: dict[str, Any], sales_map: dict[str, Any], inventory_map: dict[str, Any], document_map: dict[str, Any]) -> list[str]:
    comments: list[str] = []
    if payment_map.get("amount") and payment_map.get("date"):
        comments.append("Looks usable for payment or cash/bank movement tools.")
    if sales_map.get("counterparty") and sales_map.get("amount"):
        comments.append("Looks usable for sales or customer settlement summaries.")
    if inventory_map.get("item") and inventory_map.get("quantity"):
        comments.append("Looks usable for inventory or stock balance tools.")
    if document_map.get("number"):
        comments.append("Can be considered by document number search tools.")
    if not comments:
        comments.append("No strong business mapping identified from metadata only.")
    if "присоединенныефайлы" in entity.name.lower() or "удалить" in entity.name.lower():
        comments.append("Technical or attachment-related entity; usually avoid in business tools.")
    return comments


def build_settlement_candidates(client: OneCODataClient, entities: list[EntityInfo]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    def add(entity: EntityInfo, score: int, note: str) -> None:
        current = candidates.get(entity.name)
        row = serialize_entity(client, entity)
        row["heuristic_score"] = score
        row["heuristic_note"] = note
        if current is None or score > current.get("heuristic_score", -1):
            candidates[entity.name] = row

    sales_entities = {row["entity"]: row for row in client.discover_sales_sources(limit=20, check_data=False)}
    incoming_payment_entities = {row["entity"]: row for row in client.discover_payment_sources(direction="incoming", limit=20, check_data=False)}

    entity_map = {entity.name: entity for entity in entities}

    for entity_name, row in sales_entities.items():
        entity = entity_map.get(entity_name)
        if entity is None:
            continue
        score = int(row.get("score") or 0) + 20
        add(entity, score, "sales_candidate_for_receivables")

    for entity_name, row in incoming_payment_entities.items():
        entity = entity_map.get(entity_name)
        if entity is None:
            continue
        score = int(row.get("score") or 0) + 10
        add(entity, score, "incoming_payment_candidate_for_receivables")

    for entity in entities:
        haystack = f"{entity.name} {entity.entity_type or ''}".lower()
        bonus = 0
        if any(term in haystack for term in ("взаиморасчет", "расчетысконтрагент", "дебитор", "актсверкивзаиморасчетов")):
            bonus += 50
        if any(term in haystack for term in ("контрагент", "покупател", "реализац", "счетнаоплатупокупателю")):
            bonus += 12
        if "счетфактура" in haystack:
            bonus -= 12
        if bonus > 0:
            add(entity, bonus, "metadata_pattern_candidate_for_receivables")

    ranked = sorted(candidates.values(), key=lambda row: row.get("heuristic_score", 0), reverse=True)
    return ranked[:20]


def summarize_candidate_availability(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(rows),
        "has_data_true": 0,
        "has_data_false": 0,
        "has_data_unknown": 0,
    }
    for row in rows:
        value = row.get("has_data")
        if value is True:
            summary["has_data_true"] += 1
        elif value is False:
            summary["has_data_false"] += 1
        else:
            summary["has_data_unknown"] += 1
    return summary


def render_entity_block(entity: dict[str, Any]) -> list[str]:
    lines = [
        f"### `{entity['entity_set']}`",
        "",
        f"- Entity type: `{entity['entity_type']}`",
        f"- Possible date field: `{entity['possible_date_field']}`",
        f"- Possible number field: `{entity['possible_number_field']}`",
        f"- Possible amount fields: `{', '.join(entity['possible_amount_fields']) or '<none>'}`",
        f"- Possible counterparty fields: `{', '.join(entity['possible_counterparty_fields']) or '<none>'}`",
        f"- Possible warehouse fields: `{', '.join(entity['possible_warehouse_fields']) or '<none>'}`",
        f"- Possible currency fields: `{', '.join(entity['possible_currency_fields']) or '<none>'}`",
        "- Comments for tool developers:",
    ]
    for comment in entity["comments_for_tool_developers"]:
        lines.append(f"  - {comment}")
    lines.extend(
        [
            "",
            "| Field | Type | Nullable |",
            "|---|---|---|",
        ]
    )
    for field in entity["fields"][:60]:
        lines.append(f"| `{field['name']}` | `{field['type']}` | `{field['nullable']}` |")
    lines.append("")
    return lines


def main() -> int:
    configure_quiet_logging()
    config = prepare_live_env()
    if not config.service_url:
        print("FAIL: set ONEC_ODATA_URL or ONEC_ODATA_BASE_URL first")
        return 1

    settings = load_settings()
    client = OneCODataClient(settings)
    entities = client.list_entities(refresh=True)
    inventory_candidates = client.discover_inventory_sources(limit=20, check_data=True)
    payment_candidates = client.discover_payment_sources(direction=None, limit=20, check_data=True)
    payment_in_candidates = client.discover_payment_sources(direction="incoming", limit=10, check_data=True)
    payment_out_candidates = client.discover_payment_sources(direction="outgoing", limit=10, check_data=True)
    sales_candidates = client.discover_sales_sources(limit=20, check_data=True)

    settlement_candidates = build_settlement_candidates(client, entities)
    inventory_availability = summarize_candidate_availability(inventory_candidates)
    payment_availability = summarize_candidate_availability(payment_candidates)
    payment_in_availability = summarize_candidate_availability(payment_in_candidates)
    payment_out_availability = summarize_candidate_availability(payment_out_candidates)
    sales_availability = summarize_candidate_availability(sales_candidates)

    categorized: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        categorized[category_for_entity(entity)].append(serialize_entity(client, entity))

    payload = {
        "generated_at": now_iso(),
        "base_url": config.base_url,
        "service_url": config.service_url,
        "entity_count": len(entities),
        "categories": {name: items for name, items in categorized.items()},
        "candidate_inventory_entities": inventory_candidates,
        "candidate_inventory_availability": inventory_availability,
        "candidate_payment_entities": payment_candidates,
        "candidate_payment_availability": payment_availability,
        "candidate_payment_incoming_entities": payment_in_candidates,
        "candidate_payment_incoming_availability": payment_in_availability,
        "candidate_payment_outgoing_entities": payment_out_candidates,
        "candidate_payment_outgoing_availability": payment_out_availability,
        "candidate_sales_entities": sales_candidates,
        "candidate_sales_availability": sales_availability,
        "candidate_customer_settlement_entities": settlement_candidates,
        "known_limitations": [
            "Metadata heuristics do not guarantee that a candidate contains business rows.",
            "Some 1C publications expose technical or attachment-related entities that must be filtered by tool logic.",
            "OData publication may hide some registers or return 401 for specific entity sets even when metadata is visible.",
        ],
    }

    generated_dir = repo_root() / "docs" / "generated"
    reports_dir = repo_root() / "reports"
    json_path = generated_dir / "1C_ODATA_SCHEMA_SARYDALA.json"
    md_path = generated_dir / "1C_ODATA_SCHEMA_SARYDALA.md"
    report_path = reports_dir / "1c_schema_discovery_report.md"
    write_json(json_path, payload)

    md_lines = [
        "# 1C OData Schema: SaryDala",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Base URL: `{config.base_url}`",
        f"- Service URL: `{config.service_url}`",
        f"- Total entity count: `{len(entities)}`",
        "",
        "## Catalogs",
        "",
        f"- Total catalogs: `{len(categorized.get('Catalogs', []))}`",
        f"- Sample names: `{', '.join(item['entity_set'] for item in categorized.get('Catalogs', [])[:20])}`",
        "",
        "## Documents",
        "",
        f"- Total documents: `{len(categorized.get('Documents', []))}`",
        f"- Sample names: `{', '.join(item['entity_set'] for item in categorized.get('Documents', [])[:20])}`",
        "",
        "## Registers",
        "",
        f"- Total registers: `{len(categorized.get('Registers', []))}`",
        f"- Sample names: `{', '.join(item['entity_set'] for item in categorized.get('Registers', [])[:20])}`",
        "",
        "## Other entities",
        "",
        f"- Total other entities: `{len(categorized.get('Other entities', []))}`",
        f"- Sample names: `{', '.join(item['entity_set'] for item in categorized.get('Other entities', [])[:20])}`",
        "",
        "## Candidate inventory entities",
        "",
    ]
    for row in inventory_candidates[:10]:
        md_lines.append(f"- `{row['entity']}` score=`{row['score']}` has_data=`{row.get('has_data')}` mapped_fields=`{row.get('mapped_fields')}`")
    md_lines.extend(["", "## Candidate payment entities", ""])
    for row in payment_candidates[:10]:
        md_lines.append(
            f"- `{row['entity']}` direction=`{row.get('direction')}` account_type=`{row.get('account_type')}` "
            f"score=`{row['score']}` has_data=`{row.get('has_data')}`"
        )
    md_lines.extend(["", "## Candidate payment availability summary", ""])
    md_lines.append(f"- all payment candidates: `{payment_availability}`")
    md_lines.append(f"- incoming payment candidates: `{payment_in_availability}`")
    md_lines.append(f"- outgoing payment candidates: `{payment_out_availability}`")
    md_lines.append(f"- sales candidates: `{sales_availability}`")
    md_lines.extend(["", "## Candidate customer settlement entities", ""])
    for row in payload["candidate_customer_settlement_entities"][:10]:
        md_lines.extend(render_entity_block(row))
    md_lines.extend(["", "## Known limitations", ""])
    for item in payload["known_limitations"]:
        md_lines.append(f"- {item}")
    write_markdown(md_path, "\n".join(md_lines) + "\n")

    report_lines = [
        "# 1C Schema Discovery Report",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Base URL: `{config.base_url}`",
        f"- Total entities: `{len(entities)}`",
        f"- Inventory candidates: `{len(inventory_candidates)}`",
        f"- Payment candidates: `{len(payment_candidates)}`",
        f"- Customer settlement candidates: `{len(payload['candidate_customer_settlement_entities'])}`",
        f"- Payment candidate availability: `{payment_availability}`",
        f"- Incoming payment candidate availability: `{payment_in_availability}`",
        f"- Outgoing payment candidate availability: `{payment_out_availability}`",
        "",
        "| Artifact | Path |",
        "|---|---|",
        f"| Markdown schema | `{md_path}` |",
        f"| JSON schema | `{json_path}` |",
    ]
    write_markdown(report_path, "\n".join(report_lines) + "\n")

    print(f"OK: wrote {md_path}")
    print(f"OK: wrote {json_path}")
    print(f"OK: wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
