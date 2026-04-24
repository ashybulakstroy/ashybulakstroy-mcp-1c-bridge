from __future__ import annotations

from typing import Any


def check_document_anti_patterns(payload: dict[str, Any]) -> list[str]:
    """Возвращает список антипаттернов в данных документа."""
    issues: list[str] = []
    items = payload.get("items") or []

    if not items:
        issues.append("missing_items")

    if len(items) > 1000:
        issues.append("too_many_items_requires_batch_processing")

    if payload.get("post_after_create") and not payload.get("validated"):
        issues.append("post_without_validation")

    for idx, item in enumerate(items):
        if not item.get("name") and not item.get("item_ref"):
            issues.append(f"item_{idx}_missing_name_or_ref")
        if item.get("quantity", 0) <= 0:
            issues.append(f"item_{idx}_non_positive_quantity")

    return issues
