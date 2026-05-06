from pathlib import Path

from ashybulakstroy_mcp_1c_bridge.config import Settings
from ashybulakstroy_mcp_1c_bridge.odata import OneCODataClient


class FakeOneCODataClient(OneCODataClient):
    def __init__(self):
        settings = Settings(
            odata_url="http://fake/odata/standard.odata",
            username=None,
            password=None,
            timeout_seconds=1,
            verify_ssl=False,
            db_path=Path(":memory:"),
            max_top=500,
        )
        super().__init__(settings)
        self._fake_xml = Path(__file__).parent.joinpath("fixtures", "fake_odata_metadata.xml").read_text(encoding="utf-8")

    def get_metadata_xml(self, refresh: bool = False) -> str:
        return self._fake_xml

    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        if entity_name == "AccumulationRegister_ТоварыНаСкладах":
            rows = [
                {
                    "Номенклатура": "Цемент М400",
                    "Склад": "Основной склад",
                    "КоличествоОстаток": "3",
                    "СуммаОстаток": "7500",
                    "Период": "2026-04-24T00:00:00",
                },
                {
                    "Номенклатура": "Песок",
                    "Склад": "Основной склад",
                    "КоличествоОстаток": "20",
                    "СуммаОстаток": "40000",
                    "Период": "2026-04-24T00:00:00",
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_СписаниеСБанковскогоСчета":
            rows = [
                {
                    "Дата": "2026-04-24T10:00:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "150000",
                    "Номер": "000001",
                },
                {
                    "Дата": "2026-04-25T11:30:00",
                    "Контрагент": "ТОО Cement Trade",
                    "СуммаДокумента": "50000",
                    "Номер": "000002",
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ПоступлениеНаБанковскийСчет":
            rows = [
                {
                    "Дата": "2026-04-22T10:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "100000",
                    "Номер": "000100",
                },
                {
                    "Дата": "2026-04-24T15:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "220000",
                    "Номер": "000101",
                },
                {
                    "Дата": "2026-04-26T09:05:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "70000",
                    "Номер": "000102",
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_РеализацияТоваровУслуг":
            rows = [
                {
                    "Дата": "2026-04-20T12:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "100000",
                    "Номер": "000500",
                },
                {
                    "Дата": "2026-04-23T12:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "300000",
                    "Номер": "000501",
                },
                {
                    "Дата": "2026-04-24T13:00:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "90000",
                    "Номер": "000502",
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}


def test_list_entities_parses_fake_metadata():
    client = FakeOneCODataClient()
    entities = client.list_entities(refresh=True)

    names = [e.name for e in entities]
    assert "AccumulationRegister_ТоварыНаСкладах" in names
    assert "Catalog_Номенклатура" in names


def test_discover_inventory_sources_finds_accumulation_register():
    client = FakeOneCODataClient()

    sources = client.discover_inventory_sources(limit=3, check_data=True)

    assert sources
    assert sources[0]["entity"] == "AccumulationRegister_ТоварыНаСкладах"
    assert sources[0]["mapped_fields"]["item"] == "Номенклатура"
    assert sources[0]["mapped_fields"]["quantity"] == "КоличествоОстаток"
    assert sources[0]["has_data"] is True


def test_get_inventory_auto_normalizes_inventory_rows():
    client = FakeOneCODataClient()

    result = client.get_inventory_auto(warehouse="Основной", limit=10)

    assert result["count_returned"] == 2
    assert result["data"][0]["item"] == "Цемент М400"
    assert result["data"][0]["quantity"] == "3"
    assert result["source"]["entity"] == "AccumulationRegister_ТоварыНаСкладах"


def test_get_low_stock_items_uses_threshold():
    client = FakeOneCODataClient()

    result = client.get_low_stock_items(threshold_quantity="5", limit=10)

    assert result["count_low_stock"] == 1
    assert result["data"][0]["item"] == "Цемент М400"
    assert result["data"][0]["severity"] in {"high", "critical"}


def test_discover_payment_sources_finds_outgoing_and_incoming_documents():
    client = FakeOneCODataClient()

    outgoing = client.discover_payment_sources(direction="outgoing", limit=5, check_data=True)
    incoming = client.discover_payment_sources(direction="incoming", limit=5, check_data=True)

    assert outgoing
    assert incoming
    assert outgoing[0]["entity"] == "Document_СписаниеСБанковскогоСчета"
    assert outgoing[0]["direction"] == "outgoing"
    assert incoming[0]["entity"] == "Document_ПоступлениеНаБанковскийСчет"
    assert incoming[0]["direction"] == "incoming"


def test_get_outgoing_payments_filters_by_period_and_groups_by_counterparty():
    client = FakeOneCODataClient()

    result = client.get_payments(direction="outgoing", date_from="2026-04-24", date_to="2026-04-24", limit=10)

    assert result["count_returned"] == 1
    assert result["data"][0]["counterparty"] == "ТОО БетонПром"
    assert result["total_amount"] == "150000"
    assert result["grouped_by_counterparty"][0]["counterparty"] == "ТОО БетонПром"


def test_get_incoming_payments_filters_by_counterparty():
    client = FakeOneCODataClient()

    result = client.get_payments(direction="incoming", counterparty="БетонПром", limit=10)

    assert result["count_returned"] == 1
    assert result["data"][0]["counterparty"] == "ТОО БетонПром"
    assert result["total_amount"] == "70000"


def test_payment_summary_by_counterparty_returns_top_clients():
    client = FakeOneCODataClient()

    result = client.get_payment_summary_by_counterparty(direction="incoming", limit=10)

    assert result["direction"] == "incoming"
    assert result["counterparty_count"] == 2
    assert result["rows"][0]["counterparty"] == "ТОО Альфа Строй"
    assert result["rows"][0]["total_amount"] == "320000"
    assert result["rows"][0]["payment_count"] == 2


def test_get_unpaid_customers_summary_returns_outstanding_clients():
    client = FakeOneCODataClient()

    result = client.get_unpaid_customers_summary(date_to="2026-04-30", limit=10)

    assert result["customer_count"] == 2
    assert result["rows"][0]["counterparty"] == "ТОО Альфа Строй"
    assert result["rows"][0]["billed_amount"] == "400000"
    assert result["rows"][0]["paid_amount"] == "320000"
    assert result["rows"][0]["outstanding_amount"] == "80000"
    assert result["rows"][1]["counterparty"] == "ТОО БетонПром"
    assert result["rows"][1]["outstanding_amount"] == "20000"


def test_get_overdue_unpaid_customers_returns_debtors_older_than_three_days():
    client = FakeOneCODataClient()

    result = client.get_overdue_unpaid_customers(as_of_date="2026-04-30", threshold_days=3, limit=10)

    assert result["customer_count"] == 2
    assert result["rows"][0]["counterparty"] == "ТОО Альфа Строй"
    assert result["rows"][0]["overdue_amount"] == "80000"
    assert result["rows"][0]["typical_payment_days"] == 2.0
    assert result["rows"][1]["counterparty"] == "ТОО БетонПром"
    assert result["rows"][1]["overdue_amount"] == "20000"


def test_get_customer_payment_behavior_summary_returns_typical_days():
    client = FakeOneCODataClient()

    result = client.get_customer_payment_behavior_summary(as_of_date="2026-04-30", limit=10)

    alpha = next(row for row in result["rows"] if row["counterparty"] == "ТОО Альфа Строй")
    beton = next(row for row in result["rows"] if row["counterparty"] == "ТОО БетонПром")
    assert alpha["typical_payment_days"] == 2.0
    assert alpha["closed_invoice_count"] == 1
    assert beton["typical_payment_days"] is None
