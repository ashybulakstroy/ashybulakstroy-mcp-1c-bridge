from __future__ import annotations

from typing import Any

from .anti_patterns import check_document_anti_patterns
from .performance import check_document_performance


def validate_sales_invoice_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Бизнес-валидация реализации до создания/проведения в 1С."""
    errors: list[str] = []
    warnings: list[str] = []

    if not payload.get("counterparty") and not payload.get("counterparty_ref"):
        errors.append("missing_counterparty")

    items = payload.get("items") or []
    if not items:
        errors.append("missing_items")

    for idx, item in enumerate(items):
        quantity = item.get("quantity")
        price = item.get("price")

        if quantity is None:
            errors.append(f"item_{idx}_missing_quantity")
        elif quantity <= 0:
            errors.append(f"item_{idx}_non_positive_quantity")

        if price is not None and price < 0:
            errors.append(f"item_{idx}_negative_price")

    errors.extend(check_document_anti_patterns(payload))
    warnings.extend(check_document_performance(payload))

    return {
        "valid": len(errors) == 0,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }
