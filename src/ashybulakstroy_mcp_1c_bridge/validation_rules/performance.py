from __future__ import annotations

from typing import Any


def check_document_performance(payload: dict[str, Any]) -> list[str]:
    """Возвращает предупреждения по производительности и эксплуатационным рискам."""
    warnings: list[str] = []
    items = payload.get("items") or []

    if len(items) > 100:
        warnings.append("large_document_over_100_rows")

    if payload.get("requires_entity_lookup_per_row"):
        warnings.append("potential_query_in_loop_use_batch_lookup")

    if not payload.get("warehouse") and not payload.get("warehouse_ref"):
        warnings.append("warehouse_not_specified")

    return warnings
