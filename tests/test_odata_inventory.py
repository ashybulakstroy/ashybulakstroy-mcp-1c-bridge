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
        self.captured_queries = []

    def get_metadata_xml(self, refresh: bool = False) -> str:
        return self._fake_xml

    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        self.captured_queries.append(
            {
                "entity_name": entity_name,
                "top": top,
                "select": list(select) if select else None,
                "filter_expr": filter_expr,
                "orderby": orderby,
                "skip": skip,
            }
        )
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
                    "Ref_Key": "00000000-0000-0000-0000-000000000001",
                    "Дата": "2026-04-24T10:00:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "150000",
                    "Номер": "000001",
                    "Комментарий": "Оплата поставщику",
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000002",
                    "Дата": "2026-04-25T11:30:00",
                    "Контрагент": "ТОО Cement Trade",
                    "СуммаДокумента": "50000",
                    "Номер": "000002",
                    "Комментарий": "Аванс",
                    "Posted": False,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ПоступлениеНаБанковскийСчет":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000010",
                    "Дата": "2026-04-22T10:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "100000",
                    "Номер": "000100",
                    "Валюта": "KZT",
                    "Комментарий": "Оплата по договору",
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000011",
                    "Дата": "2026-04-24T15:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "220000",
                    "Номер": "000101",
                    "Валюта": "KZT",
                    "Комментарий": "Доплата",
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000012",
                    "Дата": "2026-04-26T09:05:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "70000",
                    "Номер": "000102",
                    "Валюта": "KZT",
                    "Комментарий": "Частичная оплата",
                    "Posted": False,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ПриходныйКассовыйОрдер":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000020",
                    "Дата": "2026-04-24T16:00:00",
                    "Контрагент": "ТОО Ромашка",
                    "СуммаДокумента": "30000",
                    "Номер": "PKO-001",
                    "Валюта": "KZT",
                    "Комментарий": "Наличный платеж",
                    "Posted": True,
                }
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_РасходныйКассовыйОрдер":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000030",
                    "Дата": "2026-04-25T09:00:00",
                    "Контрагент": "ТОО Сервис",
                    "СуммаДокумента": "20000",
                    "Номер": "RKO-001",
                    "Валюта": "KZT",
                    "Комментарий": "Подотчет",
                    "Posted": True,
                }
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_РеализацияТоваровУслуг":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000100",
                    "Дата": "2026-04-20T12:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "100000",
                    "Номер": "000500",
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000101",
                    "Дата": "2026-04-23T12:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "300000",
                    "Номер": "000501",
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000102",
                    "Дата": "2026-04-24T13:00:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "90000",
                    "Номер": "000502",
                    "Posted": False,
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


def test_search_document_by_number_finds_document_rows_with_safe_fields():
    client = FakeOneCODataClient()

    result = client.search_document_by_number(document_number="00050", limit=20)

    assert result["count_returned"] == 3
    assert result["data"][0]["document_type"] == "Document_РеализацияТоваровУслуг"
    assert result["data"][0]["number"] == "000502"
    assert result["data"][0]["counterparty"] == "ТОО БетонПром"
    assert result["data"][0]["amount"] == "90000"
    assert result["data"][0]["status"] == "not_posted"
    assert result["data"][0]["reference"] == "00000000-0000-0000-0000-000000000102"


def test_search_document_by_number_respects_type_period_and_limit_cap():
    client = FakeOneCODataClient()

    result = client.search_document_by_number(
        document_number="00010",
        document_type="Поступление",
        date_from="2026-04-24",
        date_to="2026-04-24",
        limit=50,
    )

    assert result["count_returned"] == 1
    assert result["filters_applied_in_python"]["limit"] == 20
    assert result["data"][0]["document_type"] == "Document_ПоступлениеНаБанковскийСчет"
    assert result["data"][0]["number"] == "000101"
    assert result["data"][0]["status"] == "posted"
    assert len(client.captured_queries) == 1
    assert client.captured_queries[0]["entity_name"] == "Document_ПоступлениеНаБанковскийСчет"
    assert client.captured_queries[0]["top"] == 20
    assert "substringof('00010', Номер) eq true" in str(client.captured_queries[0]["filter_expr"])
    assert "Дата ge datetime'2026-04-24T00:00:00'" in str(client.captured_queries[0]["filter_expr"])
    assert "Дата le datetime'2026-04-24T23:59:59'" in str(client.captured_queries[0]["filter_expr"])


def test_search_document_by_number_escapes_special_characters_in_filter():
    client = FakeOneCODataClient()

    result = client.search_document_by_number(document_number="A'12", document_type="Реализация", limit=5)

    assert result["count_returned"] == 0
    assert len(client.captured_queries) == 1
    assert "substringof('A''12', Номер) eq true" in str(client.captured_queries[0]["filter_expr"])


def test_search_document_by_number_unknown_type_returns_empty_without_unsafe_access():
    client = FakeOneCODataClient()

    result = client.search_document_by_number(document_number="000500", document_type="НеизвестныйТип", limit=5)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert client.captured_queries == []
    assert result["warnings"]


def test_search_document_by_number_returns_empty_when_nothing_found():
    client = FakeOneCODataClient()

    result = client.search_document_by_number(document_number="999999", document_type="Реализация", limit=5)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert len(client.captured_queries) == 1


def test_get_customer_settlements_summary_returns_safe_receivables_rows():
    client = FakeOneCODataClient()

    result = client.get_customer_settlements_summary(date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 2
    assert result["data"][0]["counterparty"] == "ТОО Альфа Строй"
    assert result["data"][0]["debt_amount"] == "80000"
    assert result["data"][0]["last_payment_date"] == "2026-04-24"
    assert result["data"][0]["overdue_days"] == 7
    assert result["data"][0]["source_document_count"] == 2
    assert result["data"][0]["source_entity"] == "Document_РеализацияТоваровУслуг"
    assert result["data"][0]["bin_or_iin"] is None
    assert result["data"][0]["currency"] is None
    assert "raw" not in result["data"][0]
    assert "http://" not in str(result)
    assert result["source_explanation"]["sales_documents_used"] == "Document_РеализацияТоваровУслуг"
    assert result["source_explanation"]["incoming_payments_used"] == "Document_ПоступлениеНаБанковскийСчет"
    assert "официальным бухгалтерским актом сверки" in result["note"]


def test_get_customer_settlements_summary_caps_limit_and_min_debt():
    client = FakeOneCODataClient()

    result = client.get_customer_settlements_summary(date_to="2026-04-30", min_debt="50000", limit=100)

    assert result["count_returned"] == 1
    assert result["filters_applied_in_python"]["limit"] == 50
    assert result["data"][0]["counterparty"] == "ТОО Альфа Строй"
    sales_query = [query for query in client.captured_queries if query["entity_name"] == "Document_РеализацияТоваровУслуг"][-1]
    incoming_query = [query for query in client.captured_queries if query["entity_name"] == "Document_ПоступлениеНаБанковскийСчет"][-1]
    assert sales_query["top"] <= 500
    assert incoming_query["top"] <= 500


def test_get_customer_settlements_summary_returns_empty_when_no_debt_matches():
    client = FakeOneCODataClient()

    result = client.get_customer_settlements_summary(date_to="2026-04-30", min_debt="1000000", limit=10)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert result["warnings"]


def test_get_customer_settlements_summary_handles_missing_sources_gracefully():
    client = FakeOneCODataClient()
    client.discover_sales_sources = lambda limit=1, check_data=True: []

    result = client.get_customer_settlements_summary(date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert "sales_documents" in result["missing_sources"]
    assert result["warnings"]
    assert result["source_explanation"]["basis"] == "summary_not_built"


def test_get_customer_settlements_summary_rejects_invalid_date_range():
    client = FakeOneCODataClient()

    try:
        client.get_customer_settlements_summary(date_from="2026-05-01", date_to="2026-04-01")
        assert False, "Expected ODataError for invalid date range"
    except Exception as exc:
        assert "date_from" in str(exc)


def test_get_customer_settlements_summary_escapes_counterparty_name_in_filters():
    client = FakeOneCODataClient()

    result = client.get_customer_settlements_summary(date_to="2026-04-30", counterparty_name="Альфа'Строй", limit=10)

    assert result["count_returned"] == 0
    sales_query = [query for query in client.captured_queries if query["entity_name"] == "Document_РеализацияТоваровУслуг"][-1]
    incoming_query = [query for query in client.captured_queries if query["entity_name"] == "Document_ПоступлениеНаБанковскийСчет"][-1]
    assert "substringof('Альфа''Строй', Контрагент) eq true" in str(sales_query["filter_expr"])
    assert "substringof('Альфа''Строй', Контрагент) eq true" in str(incoming_query["filter_expr"])


def test_get_customer_settlements_summary_rejects_invalid_min_debt():
    client = FakeOneCODataClient()

    try:
        client.get_customer_settlements_summary(date_to="2026-04-30", min_debt="not-a-number")
        assert False, "Expected ODataError for invalid min_debt"
    except Exception as exc:
        assert "min_debt" in str(exc)


def test_get_cash_bank_movements_returns_safe_rows():
    client = FakeOneCODataClient()

    result = client.get_cash_bank_movements(date_from="2026-04-24", date_to="2026-04-25", limit=10)

    assert result["count_returned"] >= 1
    first = result["data"][0]
    assert set(first.keys()) == {
        "date",
        "movement_type",
        "account_type",
        "counterparty",
        "amount",
        "currency",
        "document_type",
        "document_number",
        "purpose",
        "source_entity",
    }
    assert "http://" not in str(result)
    assert result["source_explanation"]["basis"] == "payment_documents_classified_as_bank_or_cash"


def test_get_cash_bank_movements_caps_limit():
    client = FakeOneCODataClient()

    result = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", limit=1000)

    assert result["filters_applied_in_python"]["limit"] == 100


def test_get_cash_bank_movements_filters_incoming_outgoing():
    client = FakeOneCODataClient()

    incoming = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", movement_type="incoming", limit=20)
    outgoing = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", movement_type="outgoing", limit=20)

    assert incoming["data"]
    assert outgoing["data"]
    assert all(row["movement_type"] == "incoming" for row in incoming["data"])
    assert all(row["movement_type"] == "outgoing" for row in outgoing["data"])


def test_get_cash_bank_movements_filters_bank_cash():
    client = FakeOneCODataClient()

    bank = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", account_type="bank", limit=20)
    cash = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", account_type="cash", limit=20)

    assert bank["data"]
    assert cash["data"]
    assert all(row["account_type"] == "bank" for row in bank["data"])
    assert all(row["account_type"] == "cash" for row in cash["data"])


def test_get_cash_bank_movements_filters_min_amount():
    client = FakeOneCODataClient()

    result = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", min_amount="100000", limit=20)

    assert result["data"]
    assert all(float(row["amount"]) >= 100000 for row in result["data"])


def test_get_cash_bank_movements_rejects_invalid_date_range():
    client = FakeOneCODataClient()

    try:
        client.get_cash_bank_movements(date_from="2026-05-01", date_to="2026-04-01")
        assert False, "Expected ODataError for invalid date range"
    except Exception as exc:
        assert "date_from" in str(exc)


def test_get_cash_bank_movements_rejects_invalid_movement_type():
    client = FakeOneCODataClient()

    try:
        client.get_cash_bank_movements(movement_type="sideways")
        assert False, "Expected ODataError for invalid movement_type"
    except Exception as exc:
        assert "movement_type" in str(exc)


def test_get_cash_bank_movements_rejects_invalid_account_type():
    client = FakeOneCODataClient()

    try:
        client.get_cash_bank_movements(account_type="crypto")
        assert False, "Expected ODataError for invalid account_type"
    except Exception as exc:
        assert "account_type" in str(exc)


def test_get_cash_bank_movements_escapes_counterparty_name():
    client = FakeOneCODataClient()

    result = client.get_cash_bank_movements(
        date_from="2026-04-20",
        date_to="2026-04-30",
        counterparty_name="Альфа'Строй",
        limit=20,
    )

    assert result["count_returned"] == 0
    filtered_queries = [query for query in client.captured_queries if query["filter_expr"]]
    assert filtered_queries
    assert any("substringof('Альфа''Строй', Контрагент) eq true" in str(query["filter_expr"]) for query in filtered_queries)


def test_get_cash_bank_movements_returns_empty_result():
    client = FakeOneCODataClient()

    result = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", min_amount="999999999", limit=20)

    assert result["count_returned"] == 0
    assert result["data"] == []


def test_get_cash_bank_movements_handles_missing_sources_gracefully():
    client = FakeOneCODataClient()
    client.discover_payment_sources = lambda direction=None, limit=10, check_data=True: []

    result = client.get_cash_bank_movements(date_from="2026-04-20", date_to="2026-04-30", limit=20)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert result["missing_sources"]
    assert result["warnings"]
