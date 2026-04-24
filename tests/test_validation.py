from decimal import Decimal

from ashybulakstroy_mcp_1c_bridge.validation import (
    InventoryValidationConfig,
    parse_inventory_report_text,
    validate_inventory_rows,
)


def test_parse_inventory_report_text_from_tabular_copy():
    text = """
Материальная ведомость
Номенклатура\tСклад\tКоличество\tСумма
Цемент М400\tОсновной склад\t100\t250000
Песок\tОсновной склад\t50,5\t30000,25
Итого\t\t150,5\t280000,25
"""
    rows = parse_inventory_report_text(text)

    assert rows == [
        {"item": "Цемент М400", "warehouse": "Основной склад", "quantity": "100", "amount": "250000"},
        {"item": "Песок", "warehouse": "Основной склад", "quantity": "50,5", "amount": "30000,25"},
    ]


def test_validate_inventory_rows_ok_with_tolerance():
    mcp_rows = [{"item": "Цемент М400", "warehouse": "Основной склад", "quantity": "100.0004", "amount": "250000.40"}]
    report_rows = [{"Номенклатура": "Цемент М400", "Склад": "Основной склад", "Количество": "100", "Сумма": "250000"}]

    result = validate_inventory_rows(
        mcp_rows,
        report_rows,
        InventoryValidationConfig(tolerance_quantity=Decimal("0.001"), tolerance_amount=Decimal("1")),
    )

    assert result["status"] == "ok"
    assert result["summary"]["matched_keys"] == 1
    assert result["summary"]["mismatched_keys"] == 0


def test_validate_inventory_rows_reports_missing_and_mismatch():
    mcp_rows = [
        {"item": "Цемент М400", "warehouse": "Основной склад", "quantity": "90", "amount": "250000"},
        {"item": "Арматура", "warehouse": "Основной склад", "quantity": "10", "amount": "1000"},
    ]
    report_rows = [
        {"item": "Цемент М400", "warehouse": "Основной склад", "quantity": "100", "amount": "250000"},
        {"item": "Песок", "warehouse": "Основной склад", "quantity": "5", "amount": "300"},
    ]

    result = validate_inventory_rows(mcp_rows, report_rows)

    assert result["status"] == "mismatch"
    assert result["summary"]["mismatched_keys"] == 1
    assert result["summary"]["missing_in_mcp"] == 1
    assert result["summary"]["missing_in_report"] == 1
