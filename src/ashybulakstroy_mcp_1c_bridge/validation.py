from __future__ import annotations

from dataclasses import dataclass
import re
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class InventoryValidationConfig:
    key_fields: tuple[str, ...] = ("item", "warehouse")
    tolerance_quantity: Decimal = Decimal("0.001")
    tolerance_amount: Decimal = Decimal("1.00")
    compare_amount: bool = True


def validate_inventory_rows(
    mcp_rows: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
    config: InventoryValidationConfig | None = None,
) -> dict[str, Any]:
    """Compare MCP inventory rows with manually exported/copied 1C report rows.

    Expected row fields are flexible, but the preferred normalized names are:
    item, warehouse, quantity, amount.
    """
    cfg = config or InventoryValidationConfig()
    mcp_agg = _aggregate_rows(mcp_rows, cfg.key_fields)
    report_agg = _aggregate_rows(report_rows, cfg.key_fields)
    all_keys = sorted(set(mcp_agg) | set(report_agg))

    matched: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    missing_in_mcp: list[dict[str, Any]] = []
    missing_in_report: list[dict[str, Any]] = []

    total_mcp_qty = Decimal("0")
    total_report_qty = Decimal("0")
    total_mcp_amount = Decimal("0")
    total_report_amount = Decimal("0")

    for key in all_keys:
        m = mcp_agg.get(key)
        r = report_agg.get(key)
        if m:
            total_mcp_qty += m["quantity"]
            total_mcp_amount += m["amount"]
        if r:
            total_report_qty += r["quantity"]
            total_report_amount += r["amount"]

        if m is None:
            missing_in_mcp.append(_diff_row(key, None, r, cfg))
            continue
        if r is None:
            missing_in_report.append(_diff_row(key, m, None, cfg))
            continue

        diff = _diff_row(key, m, r, cfg)
        qty_ok = abs(diff["quantity_diff_decimal"]) <= cfg.tolerance_quantity
        amount_ok = True
        if cfg.compare_amount:
            amount_ok = abs(diff["amount_diff_decimal"]) <= cfg.tolerance_amount
        if qty_ok and amount_ok:
            matched.append(_public_diff(diff))
        else:
            mismatched.append(_public_diff(diff))

    qty_total_diff = total_mcp_qty - total_report_qty
    amount_total_diff = total_mcp_amount - total_report_amount
    status = "ok"
    if missing_in_mcp or missing_in_report or mismatched:
        status = "mismatch"
    if not report_rows:
        status = "no_report_rows"
    if not mcp_rows:
        status = "no_mcp_rows"

    return {
        "status": status,
        "summary": {
            "mcp_rows": len(mcp_rows),
            "report_rows": len(report_rows),
            "matched_keys": len(matched),
            "mismatched_keys": len(mismatched),
            "missing_in_mcp": len(missing_in_mcp),
            "missing_in_report": len(missing_in_report),
            "total_mcp_quantity": _to_number(total_mcp_qty),
            "total_report_quantity": _to_number(total_report_qty),
            "total_quantity_diff": _to_number(qty_total_diff),
            "total_mcp_amount": _to_number(total_mcp_amount),
            "total_report_amount": _to_number(total_report_amount),
            "total_amount_diff": _to_number(amount_total_diff),
        },
        "settings": {
            "key_fields": list(cfg.key_fields),
            "tolerance_quantity": str(cfg.tolerance_quantity),
            "tolerance_amount": str(cfg.tolerance_amount),
            "compare_amount": cfg.compare_amount,
        },
        "mismatched": mismatched[:100],
        "missing_in_mcp": [_public_diff(x) for x in missing_in_mcp[:100]],
        "missing_in_report": [_public_diff(x) for x in missing_in_report[:100]],
        "matched_sample": matched[:20],
        "recommendations": _recommendations(status, mismatched, missing_in_mcp, missing_in_report),
    }


def _aggregate_rows(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, Any]]:
    out: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_row(row)
        key = tuple(_clean_key(normalized.get(k)) for k in key_fields)
        current = out.setdefault(key, {"key": key, "quantity": Decimal("0"), "amount": Decimal("0"), "raw_count": 0})
        current["quantity"] += _to_decimal(normalized.get("quantity"))
        current["amount"] += _to_decimal(normalized.get("amount"))
        current["raw_count"] += 1
    return out


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "item": ["item", "номенклатура", "товар", "материал", "наименование", "nomenclature", "product"],
        "warehouse": ["warehouse", "склад", "место хранения", "местохранение", "store"],
        "quantity": ["quantity", "количество", "остаток", "количество остаток", "qty"],
        "amount": ["amount", "сумма", "стоимость", "сумма остаток", "cost"],
    }
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    normalized: dict[str, Any] = {}
    for target, names in aliases.items():
        value = None
        for name in names:
            if name in lowered:
                value = lowered[name]
                break
        if value is None and target in row:
            value = row[target]
        normalized[target] = value
    return normalized


def _diff_row(key: tuple[str, ...], mcp: dict[str, Any] | None, report: dict[str, Any] | None, cfg: InventoryValidationConfig) -> dict[str, Any]:
    mcp_qty = mcp["quantity"] if mcp else Decimal("0")
    report_qty = report["quantity"] if report else Decimal("0")
    mcp_amount = mcp["amount"] if mcp else Decimal("0")
    report_amount = report["amount"] if report else Decimal("0")
    return {
        "key": {field: value for field, value in zip(cfg.key_fields, key)},
        "mcp_quantity": _to_number(mcp_qty),
        "report_quantity": _to_number(report_qty),
        "quantity_diff": _to_number(mcp_qty - report_qty),
        "quantity_diff_decimal": mcp_qty - report_qty,
        "mcp_amount": _to_number(mcp_amount),
        "report_amount": _to_number(report_amount),
        "amount_diff": _to_number(mcp_amount - report_amount),
        "amount_diff_decimal": mcp_amount - report_amount,
        "mcp_raw_count": mcp.get("raw_count") if mcp else 0,
        "report_raw_count": report.get("raw_count") if report else 0,
    }


def _public_diff(diff: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in diff.items() if not k.endswith("_decimal")}


def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _to_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _clean_key(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _recommendations(status: str, mismatched: list[dict[str, Any]], missing_in_mcp: list[dict[str, Any]], missing_in_report: list[dict[str, Any]]) -> list[str]:
    if status == "ok":
        return ["Сверка прошла: найденный MCP-источник можно перевести в verified recipe после ручного подтверждения периода и фильтров."]
    out = ["Проверьте, что дата, склад, номенклатура и вид учета в отчете 1С совпадают с параметрами MCP-запроса."]
    if missing_in_mcp:
        out.append("Есть строки отчета 1С, которых нет в MCP. Возможен неправильный источник, фильтр или разрез аналитики.")
    if missing_in_report:
        out.append("Есть строки MCP, которых нет в отчете 1С. Проверьте непроведенные документы, другой регистр или текущий период.")
    if mismatched:
        out.append("Есть количественные/суммовые расхождения. Проверьте единицы измерения, партии, характеристики, склад и дату среза.")
    return out


def parse_inventory_report_text(report_text: str) -> list[dict[str, Any]]:
    """Parse inventory report rows copied from 1C/Excel screen into normalized dictionaries."""
    if not report_text or not report_text.strip():
        return []
    lines = [line.strip() for line in report_text.replace("\ufeff", "").splitlines() if line.strip()]
    parsed_lines = [_split_report_line(line) for line in lines]
    header_index = _find_header_index(parsed_lines)
    rows: list[dict[str, Any]] = []
    if header_index is not None:
        headers = [_normalize_header(cell) for cell in parsed_lines[header_index]]
        for parts in parsed_lines[header_index + 1:]:
            if _is_total_or_noise(parts):
                continue
            row = _row_from_header(headers, parts)
            if _looks_like_inventory_row(row):
                rows.append(row)
    else:
        for parts in parsed_lines:
            if _is_total_or_noise(parts):
                continue
            row = _row_from_position(parts)
            if _looks_like_inventory_row(row):
                rows.append(row)
    return rows


def _split_report_line(line: str) -> list[str]:
    line = line.strip().strip("|")
    if "\t" in line:
        return [x.strip() for x in line.split("\t") if x.strip()]
    if ";" in line:
        return [x.strip() for x in line.split(";") if x.strip()]
    if "|" in line:
        return [x.strip() for x in line.split("|") if x.strip()]
    return [x.strip() for x in re.split(r"\s{2,}", line) if x.strip()]


def _find_header_index(lines: list[list[str]]) -> int | None:
    for i, parts in enumerate(lines[:10]):
        normalized = " ".join(_normalize_header(x) for x in parts)
        has_item = any(x in normalized for x in ["номенклатура", "товар", "материал", "наименование", "item"])
        has_qty = any(x in normalized for x in ["количество", "остаток", "qty", "quantity"])
        if has_item and has_qty:
            return i
    return None


def _normalize_header(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("\n", " ").split())


def _row_from_header(headers: list[str], parts: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for idx, value in enumerate(parts):
        if idx >= len(headers):
            continue
        target = _map_header(headers[idx])
        if target:
            row[target] = value
    if "item" not in row and parts:
        row["item"] = parts[0]
    return row


def _map_header(header: str) -> str | None:
    if any(x in header for x in ["номенклатура", "товар", "материал", "наименование", "item", "product"]):
        return "item"
    if any(x in header for x in ["склад", "место хранения", "warehouse", "store"]):
        return "warehouse"
    if any(x in header for x in ["количество", "остаток", "qty", "quantity"]):
        return "quantity"
    if any(x in header for x in ["сумма", "стоимость", "amount", "cost"]):
        return "amount"
    return None


def _row_from_position(parts: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    numeric_positions = [i for i, p in enumerate(parts) if _is_decimal_like(p)]
    if not numeric_positions:
        return row
    first_num = numeric_positions[0]
    text_parts = parts[:first_num]
    if len(text_parts) >= 2:
        row["item"] = text_parts[0]
        row["warehouse"] = text_parts[1]
    elif len(text_parts) == 1:
        row["item"] = text_parts[0]
    row["quantity"] = parts[first_num]
    if len(numeric_positions) > 1:
        row["amount"] = parts[numeric_positions[1]]
    return row


def _is_decimal_like(value: Any) -> bool:
    text = str(value).strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text))


def _is_total_or_noise(parts: list[str]) -> bool:
    joined = " ".join(parts).lower()
    if not joined:
        return True
    if joined.startswith(("итог", "всего", "отбор", "период", "организация", "склад:")):
        return True
    if "материальная ведомость" in joined:
        return True
    return False


def _looks_like_inventory_row(row: dict[str, Any]) -> bool:
    item = row.get("item")
    qty = row.get("quantity")
    amount = row.get("amount")
    if not item or str(item).strip().lower() in {"номенклатура", "товар", "наименование"}:
        return False
    return qty is not None or amount is not None
