from pathlib import Path

import httpx

from ashybulakstroy_mcp_1c_bridge.config import Settings
from ashybulakstroy_mcp_1c_bridge.odata import ODataError, OneCODataClient


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
        self.material_account_ref = "13300000-0000-0000-0000-000000000001"

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
        if entity_name == "AccumulationRegister_ТоварыНаВиртуальныхСкладах_RecordType":
            rows = [
                {
                    "Ref_Key": "vr-1",
                    "Period": "2026-04-20T12:00:00",
                    "Active": True,
                    "RecordType": "Receipt",
                    "Номенклатура": "10000000-0000-0000-0000-000000000001",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 10,
                },
                {
                    "Ref_Key": "vr-2",
                    "Period": "2026-04-21T10:00:00",
                    "Active": True,
                    "RecordType": "Receipt",
                    "Номенклатура": "10000000-0000-0000-0000-000000000002",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 20,
                },
                {
                    "Ref_Key": "vr-3",
                    "Period": "2026-04-23T12:00:00",
                    "Active": True,
                    "RecordType": "Expense",
                    "Номенклатура": "10000000-0000-0000-0000-000000000001",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 7,
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
                    "Товары": [
                        {"Содержание": "Цемент М400", "Количество": 8, "Сумма": "80000"},
                        {"Содержание": "Песок", "Количество": 2, "Сумма": "20000"},
                    ],
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000101",
                    "Дата": "2026-04-23T12:00:00",
                    "Контрагент": "ТОО Альфа Строй",
                    "СуммаДокумента": "300000",
                    "Номер": "000501",
                    "Товары": [
                        {"Содержание": "Цемент М400", "Количество": 5, "Сумма": "50000"},
                        {"Содержание": "Бокорез", "Количество": 3, "Сумма": "30000"},
                    ],
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000102",
                    "Дата": "2026-04-24T13:00:00",
                    "Контрагент": "ТОО БетонПром",
                    "СуммаДокумента": "90000",
                    "Номер": "000502",
                    "Товары": [
                        {"Содержание": "Песок", "Количество": 4, "Сумма": "40000"},
                    ],
                    "Posted": False,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_РеализацияТоваровУслуг_Товары":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000100",
                    "LineNumber": "1",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                    "Количество": 8,
                    "Сумма": "80000",
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000100",
                    "LineNumber": "2",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000002",
                    "Количество": 2,
                    "Сумма": "20000",
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000101",
                    "LineNumber": "1",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                    "Количество": 5,
                    "Сумма": "50000",
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000101",
                    "LineNumber": "2",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000003",
                    "Количество": 3,
                    "Сумма": "30000",
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000102",
                    "LineNumber": "1",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000002",
                    "Количество": 4,
                    "Сумма": "40000",
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_СчетНаОплатуПокупателю":
            rows = [
                {
                    "Ref_Key": "10000000-0000-0000-0000-000000000100",
                    "Number": "000127",
                    "Date": "2026-04-30T10:00:00",
                    "Контрагент_Key": "cp-guid-1",
                    "Организация_Key": "org-guid-1",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Ответственный_Key": "user-guid-1",
                    "СтруктурноеПодразделение_Key": "00000000-0000-0000-0000-000000000000",
                    "СтруктурнаяЕдиница": "ИП Isatay",
                    "Комментарий": "Срочный счет",
                    "СуммаДокумента": "64000",
                    "ВалютаДокумента_Key": "cur-guid-1",
                    "Posted": True,
                    "Товары": [
                        {"Содержание": "Круглая труба", "Количество": 48, "Цена": 680, "Сумма": "32640"},
                    ],
                    "Услуги": [
                        {"Содержание": "Доставка", "Количество": 1, "Цена": 4000, "Сумма": "4000"},
                    ],
                },
                {
                    "Ref_Key": "10000000-0000-0000-0000-000000000101",
                    "Number": "000128",
                    "Date": "2026-05-01T11:00:00",
                    "Контрагент_Key": "cp-guid-2",
                    "Организация_Key": "org-guid-1",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Ответственный_Key": "user-guid-2",
                    "СтруктурноеПодразделение_Key": "dep-guid-2",
                    "Комментарий": "",
                    "СуммаДокумента": "18000",
                    "ВалютаДокумента_Key": "cur-guid-1",
                    "Posted": False,
                    "Товары": [
                        {"Содержание": "Бокорез", "Количество": 3, "Цена": 6000, "Сумма": "18000"},
                    ],
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ПоступлениеТоваровУслуг":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000200",
                    "Дата": "2026-04-20T12:00:00",
                    "Контрагент": "ТОО Cement Trade",
                    "СуммаДокумента": "120000",
                    "Номер": "SUP-001",
                    "Валюта": "KZT",
                    "Товары": [
                        {"Содержание": "Цемент М400", "Номенклатура_Key": "10000000-0000-0000-0000-000000000001", "Количество": 10, "Сумма": "90000"},
                        {"Содержание": "Песок", "Номенклатура_Key": "10000000-0000-0000-0000-000000000002", "Количество": 5, "Сумма": "30000"},
                    ],
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000201",
                    "Дата": "2026-04-23T12:00:00",
                    "Контрагент": "ТОО Cement Trade",
                    "СуммаДокумента": "40000",
                    "Номер": "SUP-002",
                    "Валюта": "KZT",
                    "Услуги": [
                        {"Содержание": "Доставка", "Количество": 1, "Сумма": "40000"},
                    ],
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000202",
                    "Дата": "2026-04-24T13:00:00",
                    "Контрагент": "ТОО Сервис",
                    "СуммаДокумента": "60000",
                    "Номер": "SUP-003",
                    "Валюта": "KZT",
                    "Услуги": [
                        {"Содержание": "Сервисное обслуживание", "Количество": 1, "Сумма": "60000"},
                    ],
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000203",
                    "Дата": "2026-05-05T13:00:00",
                    "Контрагент": "ТОО Тестовый Поставщик",
                    "СуммаДокумента": "200",
                    "Номер": "MAT-001",
                    "Валюта": "KZT",
                    "Товары": [
                        {"Содержание": "Цемент М400", "Номенклатура_Key": "10000000-0000-0000-0000-000000000001", "Количество": 2, "Сумма": "200", "СчетУчетаБУ_Key": self.material_account_ref},
                    ],
                    "Posted": True,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ВводНачальныхОстатков":
            rows = [
                {
                    "Ref_Key": "opening-001",
                    "Date": "2026-04-01T09:00:00",
                    "Запасы": [
                        {
                            "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                            "Склад_Key": "20000000-0000-0000-0000-000000000001",
                            "КоличествоБУ": 10,
                            "СуммаБУ": 1000,
                            "СчетУчетаБУ_Key": self.material_account_ref,
                        }
                    ],
                }
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "AccumulationRegister_РеализацияТМЗ_RecordType":
            rows = [
                {
                    "Ref_Key": "sale-reg-1",
                    "Period": "2026-04-22T10:00:00",
                    "Recorder_Type": "StandardODATA.Document_РеализацияТоваровУслуг",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 3,
                    "Стоимость": 300,
                    "СчетУчета_Key": self.material_account_ref,
                },
                {
                    "Ref_Key": "sale-reg-2",
                    "Period": "2026-04-23T11:00:00",
                    "Recorder_Type": "StandardODATA.Document_ВозвратТоваровОтПокупателя",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 1,
                    "Стоимость": 100,
                    "СчетУчета_Key": self.material_account_ref,
                },
                {
                    "Ref_Key": "sale-reg-3",
                    "Period": "2026-05-06T09:00:00",
                    "Recorder_Type": "StandardODATA.Document_РеализацияТоваровУслуг",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000003",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 1,
                    "Стоимость": 200,
                    "СчетУчета_Key": self.material_account_ref,
                },
                {
                    "Ref_Key": "sale-reg-4",
                    "Period": "2026-05-07T09:00:00",
                    "Recorder_Type": "StandardODATA.Document_ВозвратТоваровОтПокупателя",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000003",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "Количество": 1,
                    "Стоимость": 200,
                    "СчетУчета_Key": self.material_account_ref,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_КомплектацияНоменклатуры":
            rows = [
                {
                    "Ref_Key": "comp-001",
                    "Date": "2026-05-06T08:00:00",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000003",
                    "Количество": 2,
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "СчетУчетаБУ_Key": self.material_account_ref,
                    "Комплектующие": [
                        {
                            "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                            "Количество": 4,
                            "СчетУчетаБУ_Key": self.material_account_ref,
                        }
                    ],
                },
                {
                    "Ref_Key": "comp-002",
                    "Date": "2026-05-08T10:00:00",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000002",
                    "Количество": 1,
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "СчетУчетаБУ_Key": self.material_account_ref,
                    "Комплектующие": [
                        {
                            "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                            "Количество": 2,
                            "СчетУчетаБУ_Key": self.material_account_ref,
                        }
                    ],
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ВводНачальныхОстатков_Запасы":
            rows = [
                {
                    "Ref_Key": "stock-ref-1",
                    "LineNumber": "1",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000001",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "КоличествоБУ": 3,
                },
                {
                    "Ref_Key": "stock-ref-1",
                    "LineNumber": "2",
                    "Номенклатура_Key": "10000000-0000-0000-0000-000000000002",
                    "Склад_Key": "20000000-0000-0000-0000-000000000001",
                    "КоличествоБУ": 20,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Catalog_Номенклатура":
            rows = [
                {"Ref_Key": "10000000-0000-0000-0000-000000000001", "Code": "000000001", "Description": "Цемент М400", "IsFolder": False, "Услуга": False},
                {"Ref_Key": "10000000-0000-0000-0000-000000000002", "Code": "000000002", "Description": "Песок", "IsFolder": False, "Услуга": False},
                {"Ref_Key": "10000000-0000-0000-0000-000000000003", "Code": "000000003", "Description": "Бокорез", "IsFolder": False, "Услуга": False},
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Catalog_Склады":
            rows = [
                {"Ref_Key": "20000000-0000-0000-0000-000000000001", "Description": "Основной склад"},
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_СчетФактураПолученный":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000210",
                    "Дата": "2026-04-25T10:00:00",
                    "Контрагент": "ТОО Cement Trade",
                    "СуммаДокумента": "120000",
                    "Номер": "INV-001",
                    "Валюта": "KZT",
                    "Posted": True,
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000211",
                    "Дата": "2026-04-26T11:00:00",
                    "Контрагент": "ТОО Сервис",
                    "СуммаДокумента": "60000",
                    "Номер": "INV-002",
                    "Валюта": "KZT",
                    "Posted": True,
                },
            ]
            if select:
                rows = [{k: v for k, v in row.items() if k in set(select)} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_АктСверкиВзаиморасчетов":
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000300",
                    "Number": "SV-001",
                    "Date": "2026-04-30T12:00:00",
                    "Контрагент_Key": "ТОО Cement Trade",
                    "Организация_Key": "ИП Demo",
                    "ДатаНачала": "2026-04-01T00:00:00",
                    "ДатаОкончания": "2026-04-30T00:00:00",
                    "ОстатокНаНачало": "20000",
                    "Расхождение": "0",
                    "СверкаСогласована": True,
                    "ПоДаннымОрганизации": [
                        {
                            "Дата": "2026-04-20T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000200",
                            "Документ_Type": "StandardODATA.Document_ПоступлениеТоваровУслуг",
                            "Дебет": 0,
                            "Кредит": 120000,
                        },
                        {
                            "Дата": "2026-04-23T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000201",
                            "Документ_Type": "StandardODATA.Document_ПоступлениеТоваровУслуг",
                            "Дебет": 0,
                            "Кредит": 40000,
                        },
                        {
                            "Дата": "2026-04-25T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000002",
                            "Документ_Type": "StandardODATA.Document_СписаниеСБанковскогоСчета",
                            "Дебет": 50000,
                            "Кредит": 0,
                        },
                    ],
                    "ПоДаннымКонтрагента": [
                        {
                            "Дата": "2026-04-20T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000200",
                            "Документ_Type": "StandardODATA.Document_ПоступлениеТоваровУслуг",
                            "Дебет": 120000,
                            "Кредит": 0,
                        },
                        {
                            "Дата": "2026-04-23T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000201",
                            "Документ_Type": "StandardODATA.Document_ПоступлениеТоваровУслуг",
                            "Дебет": 40000,
                            "Кредит": 0,
                        },
                        {
                            "Дата": "2026-04-25T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000002",
                            "Документ_Type": "StandardODATA.Document_СписаниеСБанковскогоСчета",
                            "Дебет": 0,
                            "Кредит": 50000,
                        },
                    ],
                },
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000301",
                    "Number": "SV-002",
                    "Date": "2026-04-30T13:00:00",
                    "Контрагент_Key": "ТОО Альфа Строй",
                    "Организация_Key": "ИП Demo",
                    "ДатаНачала": "2026-04-01T00:00:00",
                    "ДатаОкончания": "2026-04-30T00:00:00",
                    "ОстатокНаНачало": "0",
                    "Расхождение": "0",
                    "СверкаСогласована": True,
                    "ПоДаннымОрганизации": [
                        {
                            "Дата": "2026-04-20T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000100",
                            "Документ_Type": "StandardODATA.Document_РеализацияТоваровУслуг",
                            "Дебет": 100000,
                            "Кредит": 0,
                        },
                        {
                            "Дата": "2026-04-24T00:00:00",
                            "Документ": "00000000-0000-0000-0000-000000000011",
                            "Документ_Type": "StandardODATA.Document_ПоступлениеНаБанковскийСчет",
                            "Дебет": 0,
                            "Кредит": 220000,
                        },
                    ],
                    "ПоДаннымКонтрагента": [],
                },
            ]
            if select:
                allowed = set(select)
                rows = [{k: v for k, v in row.items() if k in allowed} for row in rows]
            return {"entity": entity_name, "count_returned": min(len(rows), top), "top_applied": top, "data": rows[:top]}
        return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}


class FakeIsatayKnowledgeClient(FakeOneCODataClient):
    def __init__(self):
        settings = Settings(
            odata_url="http://fake/Isatay/odata/standard.odata",
            username=None,
            password=None,
            timeout_seconds=1,
            verify_ssl=False,
            db_path=Path(":memory:"),
            max_top=500,
        )
        OneCODataClient.__init__(self, settings)
        self._fake_xml = Path(__file__).parent.joinpath("fixtures", "fake_odata_metadata.xml").read_text(encoding="utf-8")
        self.captured_queries = []
        self.material_account_ref = "13300000-0000-0000-0000-000000000001"

    def get_metadata_xml(self, refresh: bool = False) -> str:
        return self._fake_xml

    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        return FakeOneCODataClient.query_entity(
            self,
            entity_name,
            top=top,
            select=select,
            filter_expr=filter_expr,
            orderby=orderby,
            skip=skip,
        )


class TimeoutDiagnosticsClient(FakeOneCODataClient):
    def __init__(self, *, host_resolved: bool, tcp_reachable: bool):
        super().__init__()
        self._host_resolved = host_resolved
        self._tcp_reachable = tcp_reachable

    @staticmethod
    def _fake_timeout(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    def _can_resolve_host(self, host: str) -> bool:
        return self._host_resolved

    def _can_connect_tcp(self, host: str, port: int) -> bool:
        return self._tcp_reachable


class TimeoutDiagnosticsODataClient(OneCODataClient):
    def __init__(self, *, host_resolved: bool, tcp_reachable: bool):
        settings = Settings(
            odata_url="http://fake-host/odata/standard.odata",
            username=None,
            password=None,
            timeout_seconds=1,
            verify_ssl=False,
            db_path=Path(":memory:"),
            max_top=500,
        )
        super().__init__(settings)
        self._host_resolved = host_resolved
        self._tcp_reachable = tcp_reachable

    def _can_resolve_host(self, host: str) -> bool:
        return self._host_resolved

    def _can_connect_tcp(self, host: str, port: int) -> bool:
        return self._tcp_reachable


class EndpointDownWizardClient(FakeOneCODataClient):
    def check_endpoint_health(self, *, check_metadata: bool = False) -> dict[str, object]:
        return {
            "host": "fake",
            "port": 80,
            "host_resolvable": True,
            "tcp_reachable": False,
            "server_alive": False,
            "odata_reachable": False if check_metadata else None,
            "metadata_readable": False if check_metadata else None,
            "details": "simulated endpoint down",
        }

    def get_metadata_xml(self, refresh: bool = False) -> str:
        raise AssertionError("get_metadata_xml should not be called when endpoint is down")


class FakeOneCODataClientRejectingDocumentFilter(FakeOneCODataClient):
    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        if entity_name == "Document_РеализацияТоваровУслуг" and filter_expr:
            raise ODataError("Ошибка при разборе опции запроса $filter")
        return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)


class FakeOneCODataClientRejectingDocumentFilterAndFallbackAccess(FakeOneCODataClient):
    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        if entity_name == "Document_РеализацияТоваровУслуг" and filter_expr:
            raise ODataError("Ошибка при разборе опции запроса $filter")
        if entity_name == "Document_РеализацияТоваровУслуг" and not filter_expr:
            raise ODataError('Ошибка OData запроса: HTTP 401: {"odata.error":{"code":"20","message":{"lang":"ru","value":"Доступ запрещен"}}}')
        return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)


class FakeOneCODataClient2009Namespace(FakeOneCODataClient):
    def get_metadata_xml(self, refresh: bool = False) -> str:
        return self._fake_xml.replace(
            "http://schemas.microsoft.com/ado/2008/09/edm",
            "http://schemas.microsoft.com/ado/2009/11/edm",
        )


class FakeOneCODataClientPaymentFallback(FakeOneCODataClient):
    def discover_payment_sources(self, direction: str | None = None, limit: int = 10, check_data: bool = True):
        if direction == "incoming":
            return [
                {
                    "entity": "Document_ПустойИсточникОплат",
                    "direction": "incoming",
                    "score": 200,
                    "confidence": "high",
                    "reasons": ["test:empty-first"],
                    "mapped_fields": {
                        "counterparty": "Контрагент",
                        "amount": "СуммаДокумента",
                        "date": "Дата",
                        "number": "Номер",
                        "currency": "Валюта",
                        "purpose": "Комментарий",
                    },
                },
                {
                    "entity": "Document_ПоступлениеНаБанковскийСчет",
                    "direction": "incoming",
                    "score": 180,
                    "confidence": "high",
                    "reasons": ["test:second-with-data"],
                    "mapped_fields": {
                        "counterparty": "Контрагент",
                        "amount": "СуммаДокумента",
                        "date": "Дата",
                        "number": "Номер",
                        "currency": "Валюта",
                        "purpose": "Комментарий",
                    },
                },
            ][:limit]
        return super().discover_payment_sources(direction=direction, limit=limit, check_data=check_data)


class FakeOneCODataClientPaymentNoData(FakeOneCODataClient):
    def discover_payment_sources(self, direction: str | None = None, limit: int = 10, check_data: bool = True):
        base = super().discover_payment_sources(direction=direction, limit=limit, check_data=check_data)
        rows = []
        for row in base:
            cloned = dict(row)
            cloned["has_data"] = False
            rows.append(cloned)
        return rows

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
        return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}


class FakeOneCODataClientPaymentSectionsFirst(FakeOneCODataClient):
    def discover_payment_sources(self, direction: str | None = None, limit: int = 10, check_data: bool = True):
        if direction == "incoming":
            return [
                {
                    "entity": "Document_ПоступлениеНаБанковскийСчет_РасшифровкаПлатежа",
                    "direction": "incoming",
                    "score": 220,
                    "confidence": "high",
                    "reasons": ["test:section-first"],
                    "mapped_fields": {
                        "counterparty": "Контрагент",
                        "amount": "СуммаПлатежа",
                        "date": "Дата",
                        "number": "Номер",
                        "currency": "Валюта",
                        "purpose": "Комментарий",
                    },
                },
                {
                    "entity": "Document_ПоступлениеНаБанковскийСчет",
                    "direction": "incoming",
                    "score": 180,
                    "confidence": "high",
                    "reasons": ["test:top-level-second"],
                    "mapped_fields": {
                        "counterparty": "Контрагент",
                        "amount": "СуммаДокумента",
                        "date": "Дата",
                        "number": "Номер",
                        "currency": "Валюта",
                        "purpose": "Комментарий",
                    },
                },
            ][:limit]
        return super().discover_payment_sources(direction=direction, limit=limit, check_data=check_data)


class FakeOneCODataClientPaymentCombinedRecent(FakeOneCODataClient):
    def discover_payment_sources(self, direction: str | None = None, limit: int = 10, check_data: bool = True):
        if direction == "incoming":
            return [
                {
                    "entity": "Document_ПоступлениеНаБанковскийСчет",
                    "direction": "incoming",
                    "score": 200,
                    "confidence": "high",
                    "reasons": ["test:bank-source"],
                    "mapped_fields": {
                        "counterparty": "Контрагент",
                        "amount": "СуммаДокумента",
                        "date": "Дата",
                        "number": "Номер",
                        "currency": "Валюта",
                        "purpose": "Комментарий",
                    },
                },
                {
                    "entity": "Document_ОплатаОтПокупателяПлатежнойКартой",
                    "direction": "incoming",
                    "score": 190,
                    "confidence": "high",
                    "reasons": ["test:card-source"],
                    "mapped_fields": {
                        "counterparty": "Контрагент",
                        "amount": "СуммаДокумента",
                        "date": "Дата",
                        "number": "Номер",
                        "currency": "Валюта",
                        "purpose": "Комментарий",
                    },
                },
            ][:limit]
        return super().discover_payment_sources(direction=direction, limit=limit, check_data=check_data)

    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        if entity_name == "Document_ОплатаОтПокупателяПлатежнойКартой":
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
            rows = [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000099",
                    "Дата": "2026-05-09T20:05:27",
                    "Контрагент": "Розничная выручка",
                    "СуммаДокумента": "23770",
                    "Номер": "0000000986",
                    "Валюта": "KZT",
                    "Комментарий": "Оплата по карте",
                    "Posted": True,
                }
            ]
            return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": rows[:top]}
        return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)


class FakeOneCODataClientSalesTailPaging(FakeOneCODataClient):
    def discover_sales_sources(self, limit: int = 10, check_data: bool = True):
        return [
            {
                "entity": "Document_РеализацияТоваровУслуг",
                "score": 300,
                "confidence": "high",
                "reasons": ["test:tail-paging"],
                "mapped_fields": {
                    "counterparty": "Контрагент",
                    "amount": "СуммаДокумента",
                    "date": "Дата",
                    "number": "Номер",
                    "organization": "Организация",
                },
            }
        ][:limit]

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
        if entity_name != "Document_РеализацияТоваровУслуг":
            return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)
        if filter_expr:
            raise ODataError("Операция не разрешена в предложении \"ГДЕ\"")
        if top == 1:
            if skip == 0:
                return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "0000000500", "Дата": "2023-12-02T11:07:13"}]}
            if skip == 250:
                return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "0000001287", "Дата": "2026-05-09T09:00:57"}]}
            return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}
        if skip == 0:
            rows = [
                {
                    "Ref_Key": "old-1",
                    "Дата": "2023-12-02T11:07:13",
                    "Контрагент": "Старый покупатель",
                    "СуммаДокумента": "12155",
                    "Номер": "0000000500",
                }
            ]
            return {"entity": entity_name, "count_returned": len(rows), "top_applied": top, "data": rows}
        if skip == 250:
            rows = [
                {
                    "Ref_Key": "new-1",
                    "Дата": "2026-05-09T09:00:57",
                    "Контрагент": "GASYRBEK ИП",
                    "СуммаДокумента": "50550",
                    "Номер": "0000001287",
                },
                {
                    "Ref_Key": "new-2",
                    "Дата": "2026-05-09T14:05:35",
                    "Контрагент": "LOFT GROOT ТОО",
                    "СуммаДокумента": "13900",
                    "Номер": "0000001288",
                },
            ]
            return {"entity": entity_name, "count_returned": len(rows), "top_applied": top, "data": rows}
        return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}


class FakeOneCODataClientPurchaseTailPaging(FakeOneCODataClient):
    def discover_purchase_sources(self, limit: int = 10, check_data: bool = True):
        return [
            {
                "entity": "Document_СчетФактураПолученный",
                "score": 210,
                "confidence": "high",
                "reasons": ["test:invoice-tail"],
                "mapped_fields": {
                    "counterparty": "Контрагент",
                    "amount": "СуммаДокумента",
                    "date": "Дата",
                    "number": "Номер",
                    "currency": "Валюта",
                },
            },
            {
                "entity": "Document_ПоступлениеТоваровУслуг",
                "score": 205,
                "confidence": "high",
                "reasons": ["test:receipt-tail"],
                "mapped_fields": {
                    "counterparty": "Контрагент",
                    "amount": "СуммаДокумента",
                    "date": "Дата",
                    "number": "Номер",
                    "currency": "Валюта",
                },
            },
        ][:limit]

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
        if entity_name == "Document_СчетФактураПолученный":
            if filter_expr:
                raise ODataError("Операция не разрешена в предложении \"ГДЕ\"")
            if top == 1:
                if skip == 0:
                    return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "INV-0001", "Дата": "2024-01-01T10:00:00"}]}
                if 0 < skip < 200:
                    return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "INV-MID", "Дата": "2025-01-01T10:00:00"}]}
                if skip >= 100:
                    return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "0000000279", "Дата": "2026-05-08T15:24:42"}]}
                return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}
            if skip >= 100:
                rows = [
                    {
                        "Ref_Key": "inv-late-1",
                        "Дата": "2026-05-08T15:24:42",
                        "Контрагент": "Жакко Караганда",
                        "СуммаДокумента": "1527105",
                        "Номер": "0000000279",
                        "Валюта": "KZT",
                        "Posted": True,
                    }
                ]
                return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": rows[:top]}
            return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}
        if entity_name == "Document_ПоступлениеТоваровУслуг":
            if filter_expr:
                raise ODataError("Операция не разрешена в предложении \"ГДЕ\"")
            if top == 1:
                if skip == 0:
                    return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "SUP-0001", "Дата": "2024-01-01T11:00:00"}]}
                if 0 < skip < 200:
                    return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "SUP-MID", "Дата": "2025-01-01T11:00:00"}]}
                if skip >= 100:
                    return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": [{"Номер": "0000000272", "Дата": "2026-05-06T20:07:09"}]}
                return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}
            if skip >= 100:
                rows = [
                    {
                        "Ref_Key": "sup-late-1",
                        "Дата": "2026-05-06T20:07:09",
                        "Контрагент": "Алматинский метизный завод ТОО",
                        "СуммаДокумента": "1076550",
                        "Номер": "0000000272",
                        "Валюта": "KZT",
                        "Posted": True,
                    }
                ]
                return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": rows[:top]}
            return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}
        return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)


class FakeOneCODataClientMaterialFilterFallback(FakeOneCODataClient):
    def query_entity(self, entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        if entity_name in {
            "Document_ПоступлениеТоваровУслуг",
            "AccumulationRegister_РеализацияТМЗ_RecordType",
            "Document_КомплектацияНоменклатуры",
        } and filter_expr:
            raise ODataError("Ошибка OData запроса: HTTP 500: Internal Server Error")
        if entity_name in {
            "Document_ПоступлениеТоваровУслуг",
            "AccumulationRegister_РеализацияТМЗ_RecordType",
            "Document_КомплектацияНоменклатуры",
        } and skip > 0:
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
            return {"entity": entity_name, "count_returned": 0, "top_applied": top, "data": []}
        return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)


class FakeOneCODataClientAmbiguousReceiptNumber(FakeOneCODataClient):
    def _discover_document_search_candidates(self, document_type: str | None = None, limit: int | None = None):
        ranked = super()._discover_document_search_candidates(document_type=document_type, limit=None)
        if document_type == "Поступление":
            ranked.sort(
                key=lambda row: 0 if row["entity"] == "Document_ПоступлениеТоваровУслуг" else 1
            )
        if limit is None or limit <= 0:
            return ranked
        return ranked[:limit]

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
        if entity_name == "Document_ПоступлениеНаБанковскийСчет":
            rows = [
                {
                    "Ref_Key": "bank-0247",
                    "Дата": "2026-05-02T12:00:00",
                    "Контрагент": "KASPI BANK АО",
                    "СуммаДокумента": "112.24",
                    "Номер": "0000000247",
                    "Валюта": "KZT",
                    "Комментарий": "Банковое поступление",
                    "Posted": True,
                }
            ]
            return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": rows[:top]}
        if entity_name == "Document_ПоступлениеТоваровУслуг":
            rows = [
                {
                    "Ref_Key": "purchase-0247",
                    "Дата": "2026-04-30T20:08:25",
                    "Контрагент": "Кауменова К.К. ИП",
                    "СуммаДокумента": "100000",
                    "Номер": "0000000247",
                    "Валюта": "KZT",
                    "Posted": True,
                }
            ]
            return {"entity": entity_name, "count_returned": 1, "top_applied": top, "data": rows[:top]}
        return super().query_entity(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)


def test_list_entities_parses_fake_metadata():
    client = FakeOneCODataClient()
    entities = client.list_entities(refresh=True)

    names = [e.name for e in entities]
    assert "AccumulationRegister_ТоварыНаСкладах" in names
    assert "Catalog_Номенклатура" in names


def test_list_entities_parses_2009_11_namespace_metadata():
    client = FakeOneCODataClient2009Namespace()
    entities = client.list_entities(refresh=True)

    names = [e.name for e in entities]
    assert "AccumulationRegister_ТоварыНаСкладах" in names
    assert "Catalog_Номенклатура" in names


def test_timeout_reports_dead_server_when_host_port_unreachable():
    client = TimeoutDiagnosticsODataClient(host_resolved=True, tcp_reachable=False)
    client.client.get = lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))

    try:
        client.get_metadata_xml(refresh=True)
        assert False, "expected ODataError"
    except ODataError as exc:
        text = str(exc)
        assert "OData endpoint недоступен" in text
        assert "порт сервера недоступен" in text


def test_timeout_reports_live_host_but_slow_odata_service():
    client = TimeoutDiagnosticsODataClient(host_resolved=True, tcp_reachable=True)
    client.client.get = lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))

    try:
        client.get_metadata_xml(refresh=True)
        assert False, "expected ODataError"
    except ODataError as exc:
        text = str(exc)
        assert "OData endpoint недоступен" in text
        assert "Хост живой" in text
        assert "не ответила" in text


def test_check_endpoint_health_reports_fast_network_state_without_metadata():
    client = TimeoutDiagnosticsODataClient(host_resolved=True, tcp_reachable=True)

    result = client.check_endpoint_health(check_metadata=False)

    assert result["host"] == "fake-host"
    assert result["port"] == 80
    assert result["host_resolvable"] is True
    assert result["tcp_reachable"] is True
    assert result["server_alive"] is True
    assert result["odata_reachable"] is None


def test_setup_wizard_reports_endpoint_down_and_skips_metadata_read():
    client = EndpointDownWizardClient()

    result = client.setup_wizard(check_live_entities=False, live_limit=5)

    assert result["status"] == "error"
    assert result["endpoint_health"]["server_alive"] is False
    endpoint_check = next(check for check in result["checks"] if check["name"] == "endpoint connectivity")
    assert endpoint_check["status"] == "error"
    metadata_check = next(check for check in result["checks"] if check["name"] == "$metadata readable")
    assert "skipped" in str(metadata_check["details"])


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
    quantities = {row["item"]: row["quantity"] for row in result["data"]}
    assert quantities["Цемент М400"] == "3"
    assert result["source"]["entity"] == "AccumulationRegister_ТоварыНаВиртуальныхСкладах_RecordType"


def test_get_inventory_auto_uses_virtual_register_stock_balance():
    client = FakeOneCODataClient()

    result = client.get_inventory_auto(limit=10)

    quantities = {row["item"]: row["quantity"] for row in result["data"]}
    assert quantities["Цемент М400"] == "3"
    assert quantities["Песок"] == "20"


def test_get_sales_item_picker_view_returns_code_name_and_stock():
    client = FakeOneCODataClient()

    result = client.get_sales_item_picker_view(as_of_date="2026-05-31", limit=10)

    assert result["count_returned"] == 3
    assert result["data"][0] == {"code": "000000001", "name": "Цемент М400", "stock": "3"}
    assert result["data"][1] == {"code": "000000002", "name": "Песок", "stock": "1"}
    assert result["data"][2] == {"code": "000000003", "name": "Бокорез", "stock": "0"}


def test_get_sales_item_picker_view_only_with_stock_filters_zero_balances():
    client = FakeOneCODataClient()

    result = client.get_sales_item_picker_view(as_of_date="2026-05-31", only_with_stock=True, limit=10)

    assert [row["name"] for row in result["data"]] == ["Цемент М400", "Песок"]
    assert all(row["stock"] != "0" for row in result["data"])


def test_get_sales_item_picker_view_matches_numeric_code_without_leading_zeros():
    client = FakeOneCODataClient()

    result = client.get_sales_item_picker_view(as_of_date="2026-05-31", search_text="1", limit=10)

    assert result["count_returned"] == 1
    assert result["data"][0] == {"code": "000000001", "name": "Цемент М400", "stock": "3"}


def test_knowledge_default_profile_is_loaded_for_fake_client():
    client = FakeOneCODataClient()

    bundle = client._load_knowledge_bundle()
    sales_knowledge = client._get_business_knowledge("sales")
    inventory_knowledge = client._get_business_knowledge("inventory")
    material_knowledge = client._get_business_knowledge("material_statement")

    assert bundle["profile_id"] == "default"
    assert "Document_РеализацияТоваровУслуг" in sales_knowledge["discovery"]["preferred_entities"]
    assert inventory_knowledge["picker"]["catalog_entity"] == "Catalog_Номенклатура"
    assert material_knowledge["account_code"] == "1330"


def test_knowledge_isatay_profile_override_is_loaded():
    client = FakeIsatayKnowledgeClient()

    bundle = client._load_knowledge_bundle()
    inventory_knowledge = client._get_business_knowledge("inventory")

    assert bundle["profile_id"] == "isatay"
    assert inventory_knowledge["picker"]["warehouse_name"] == "Основной склад"
    assert inventory_knowledge["picker"]["stock_mode"] == "hybrid"


def test_discover_payment_sources_uses_knowledge_preferred_entities():
    client = FakeOneCODataClient()

    result = client.discover_payment_sources(limit=5, check_data=False)

    entities = [row["entity"] for row in result]
    assert "Document_ПоступлениеНаБанковскийСчет" in entities
    assert "Document_СписаниеСБанковскогоСчета" in entities


def test_discover_purchase_sources_uses_knowledge_preferred_entities():
    client = FakeOneCODataClient()

    result = client.discover_purchase_sources(limit=5, check_data=False)

    entities = [row["entity"] for row in result]
    assert "Document_ПоступлениеТоваровУслуг" in entities


def test_get_top_selling_items_with_stock_returns_top_rows_with_stock():
    client = FakeOneCODataClient()

    result = client.get_top_selling_items_with_stock(
        date_from="2026-04-20",
        date_to="2026-04-24",
        limit=10,
    )

    assert result["count_returned"] == 3
    assert result["data"][0]["code"] == "000000001"
    assert result["data"][0]["item"] == "Цемент М400"
    assert result["data"][0]["quantity_sold"] == "13"
    assert result["data"][0]["stock"] == "3"
    assert result["data"][1]["code"] == "000000002"
    assert result["data"][1]["item"] == "Песок"
    assert result["data"][1]["quantity_sold"] == "6"
    assert result["data"][1]["stock"] == "20"
    assert result["data"][2]["code"] == "000000003"
    assert result["data"][2]["item"] == "Бокорез"
    assert result["data"][2]["quantity_sold"] == "3"
    assert result["data"][2]["stock"] == "0"


def test_get_top_selling_items_with_stock_only_with_stock_filters_zero_rows():
    client = FakeOneCODataClient()

    result = client.get_top_selling_items_with_stock(
        date_from="2026-04-20",
        date_to="2026-04-24",
        limit=10,
        only_with_stock=True,
    )

    assert [row["item"] for row in result["data"]] == ["Цемент М400", "Песок"]
    assert all(row["stock"] != "0" for row in result["data"])


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


def test_discover_payment_sources_without_direction_returns_candidates():
    client = FakeOneCODataClient()

    sources = client.discover_payment_sources(direction=None, limit=10, check_data=True)

    assert sources
    directions = {row["direction"] for row in sources}
    assert "incoming" in directions
    assert "outgoing" in directions


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


def test_get_payments_falls_back_to_next_safe_source_with_data():
    client = FakeOneCODataClientPaymentFallback()

    result = client.get_payments(direction="incoming", limit=10)

    assert result["count_returned"] == 3
    assert result["source"]["entity"] == "Document_ПоступлениеНаБанковскийСчет"
    assert result["source_candidates_checked"] == ["Document_ПоступлениеНаБанковскийСчет"]


def test_get_payments_marks_no_data_when_all_safe_sources_are_empty():
    client = FakeOneCODataClientPaymentNoData()

    result = client.get_payments(direction="incoming", limit=10)

    assert result["count_returned"] == 0
    assert result["no_data_in_checked_sources"] is True
    assert result["source_candidates_checked"]
    assert any("не найдено строк" in warning.lower() for warning in result["warnings"])


def test_get_payments_prefers_top_level_documents_over_sections():
    client = FakeOneCODataClientPaymentSectionsFirst()

    result = client.get_payments(direction="incoming", limit=10)

    assert result["count_returned"] == 3
    assert result["source"]["entity"] == "Document_ПоступлениеНаБанковскийСчет"
    assert result["source_candidates_checked"] == ["Document_ПоступлениеНаБанковскийСчет"]
    assert result["source_candidates_mode"] == "preferred_top_level_documents"


def test_get_payments_combines_safe_sources_and_returns_latest_rows_first():
    client = FakeOneCODataClientPaymentCombinedRecent()

    result = client.get_payments(direction="incoming", limit=10)

    assert result["count_returned"] >= 4
    assert result["data"][0]["number"] == "0000000986"
    assert result["data"][0]["counterparty"] == "Розничная выручка"
    assert "Document_ПоступлениеНаБанковскийСчет" in result["source_entities_used"]
    assert "Document_ОплатаОтПокупателяПлатежнойКартой" in result["source_entities_used"]


def test_payment_summary_by_counterparty_returns_top_clients():
    client = FakeOneCODataClient()

    result = client.get_payment_summary_by_counterparty(direction="incoming", limit=10)

    assert result["direction"] == "incoming"
    assert result["counterparty_count"] == 3
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
    assert len(client.captured_queries) >= 1
    assert any(query["entity_name"] == "Document_ПоступлениеНаБанковскийСчет" for query in client.captured_queries)
    assert client.captured_queries[0]["top"] >= 20
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


def test_get_purchase_document_details_returns_header_and_lines():
    client = FakeOneCODataClient()

    result = client.get_purchase_document_details(document_number="SUP-001", max_lines=20)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["document_type"] == "Document_ПоступлениеТоваровУслуг"
    assert row["document_number"] == "SUP-001"
    assert row["counterparty"] == "ТОО Cement Trade"
    assert row["amount"] == "120000"
    assert row["line_count"] == 2
    assert row["section_counts"]["goods"] == 2
    assert row["lines"][0]["name"] == "Цемент М400"
    assert row["lines"][0]["quantity"] == 10
    assert row["lines"][0]["amount"] == "90000"


def test_get_purchase_document_details_returns_empty_when_document_not_found():
    client = FakeOneCODataClient()

    result = client.get_purchase_document_details(document_number="SUP-999", max_lines=20)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert "не найден" in result["note"].lower()


def test_get_purchase_receipts_summary_returns_supplier_and_items_by_period():
    client = FakeOneCODataClient()

    result = client.get_purchase_receipts_summary(date_from="2026-04-20", date_to="2026-04-30", limit=10, items_per_document=5)

    assert result["count_returned"] == 4
    assert result["document_count_returned"] == 3
    top = result["data"][0]
    assert top["date"] == "2026-04-24"
    assert top["document_number"] == "SUP-003"
    assert top["supplier"] == "ТОО Сервис"
    assert top["item"] == "Сервисное обслуживание"
    assert top["quantity"] == 1
    assert top["amount"] == 60000.0


def test_get_purchase_receipts_summary_filters_by_item_name():
    client = FakeOneCODataClient()

    result = client.get_purchase_receipts_summary(date_from="2026-04-20", date_to="2026-04-30", item_name="Цемент", limit=10)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["document_number"] == "SUP-001"
    assert row["item"] == "Цемент М400"


def test_get_sales_document_details_returns_header_and_lines():
    client = FakeOneCODataClient()

    result = client.get_sales_document_details(document_number="000500", max_lines=20)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["document_type"] == "Document_РеализацияТоваровУслуг"
    assert row["document_number"] == "000500"
    assert row["counterparty"] == "ТОО Альфа Строй"
    assert row["section_counts"]["goods"] == 2
    assert row["lines"][0]["name"] == "Цемент М400"
    assert row["lines"][0]["quantity"] == 8
    assert row["lines"][0]["amount"] == "80000"


def test_get_sales_receipts_summary_returns_flat_rows():
    client = FakeOneCODataClient()

    result = client.get_sales_receipts_summary(date_from="2026-04-20", date_to="2026-04-30", limit=10, items_per_document=5)

    assert result["count_returned"] == 5
    assert result["document_count_returned"] == 3
    top = result["data"][0]
    assert top["date"] == "2026-04-24"
    assert top["document_number"] == "000502"
    assert top["counterparty"] == "ТОО БетонПром"
    assert top["item"] == "Песок"
    assert top["quantity"] == 4
    assert top["amount"] == 40000.0


def test_get_sales_receipts_summary_filters_by_item_name():
    client = FakeOneCODataClient()

    result = client.get_sales_receipts_summary(date_from="2026-04-20", date_to="2026-04-30", item_name="Бокорез", limit=10)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["document_number"] == "000501"
    assert row["item"] == "Бокорез"


def test_get_sales_journal_view_returns_screen_like_rows():
    client = FakeOneCODataClient()

    result = client.get_sales_journal_view(date_from="2026-04-20", date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 3
    top = result["data"][0]
    assert top["date"] == "2026-04-24T13:00:00"
    assert top["date_only"] == "2026-04-24"
    assert top["document_number"] == "000502"
    assert top["counterparty"] == "ТОО БетонПром"
    assert top["amount"] == "90000"
    assert top["operation_type_display"] == "Реализация (Товары, услуги)"
    assert top["source_entity"] == "Document_РеализацияТоваровУслуг"


def test_get_customer_invoice_journal_view_returns_screen_like_rows():
    client = FakeOneCODataClient()
    original_resolve_reference_value = client._resolve_reference_value
    client._resolve_reference_value = lambda field_name, value: {  # type: ignore[method-assign]
        ("Организация_Key", "org-guid-1"): "ИП Isatay",
        ("Склад_Key", "20000000-0000-0000-0000-000000000001"): "Основной склад",
        ("Ответственный_Key", "user-guid-1"): "Бекболат",
        ("Ответственный_Key", "user-guid-2"): "Сапар",
        ("ВалютаДокумента_Key", "cur-guid-1"): "KZT",
    }.get((field_name, value), original_resolve_reference_value(field_name, value))
    client._resolve_counterparty_info = lambda value: {  # type: ignore[method-assign]
        "cp-guid-1": {"display": "МПРО", "bin_or_iin": "123456789012"},
        "cp-guid-2": {"display": "ТОО БетонПром", "bin_or_iin": None},
    }.get(value, {"display": value, "bin_or_iin": None})

    result = client.get_customer_invoice_journal_view(date_from="2026-04-20", date_to="2026-05-30", limit=10)

    assert result["count_returned"] == 2
    top = result["data"][0]
    assert top["document_number"] == "000128"
    assert top["counterparty"] == "ТОО БетонПром"
    assert top["amount"] == "18000"
    assert top["warehouse"] == "Основной склад"
    assert top["source_entity"] == "Document_СчетНаОплатуПокупателю"


def test_get_customer_invoice_details_returns_header_and_lines():
    client = FakeOneCODataClient()
    original_resolve_reference_value = client._resolve_reference_value
    client._resolve_reference_value = lambda field_name, value: {  # type: ignore[method-assign]
        ("Организация_Key", "org-guid-1"): "ИП Isatay",
        ("Склад_Key", "20000000-0000-0000-0000-000000000001"): "Основной склад",
        ("Ответственный_Key", "user-guid-1"): "Бекболат",
        ("ТипЦен_Key", None): None,
        ("ВалютаДокумента_Key", "cur-guid-1"): "KZT",
    }.get((field_name, value), original_resolve_reference_value(field_name, value))
    client._resolve_counterparty_info = lambda value: {  # type: ignore[method-assign]
        "cp-guid-1": {"display": "МПРО", "bin_or_iin": "123456789012"},
    }.get(value, {"display": value, "bin_or_iin": None})

    result = client.get_customer_invoice_details(document_number="000127", max_lines=10)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["document_type"] == "Document_СчетНаОплатуПокупателю"
    assert row["document_number"] == "000127"
    assert row["counterparty"] == "МПРО"
    assert row["warehouse"] == "Основной склад"
    assert row["structural_unit"] == "ИП Isatay"
    assert row["responsible"] == "Бекболат"
    assert row["currency"] == "KZT"
    assert row["section_counts"]["goods"] == 1
    assert row["section_counts"]["services"] == 1
    assert row["lines"][0]["section_display"] == "ТМЗ"
    assert row["lines"][0]["name"] == "Круглая труба"
    assert row["lines"][1]["section_display"] == "Услуги"
    assert row["lines"][1]["name"] == "Доставка"


def test_get_sales_management_summary_returns_totals_and_top_lists():
    client = FakeOneCODataClient()

    result = client.get_sales_management_summary(date_from="2026-04-20", date_to="2026-04-30", limit=5)

    assert result["summary"]["total_documents"] == 3
    assert result["summary"]["total_sales_amount"] == "490000"
    assert result["top_items"][0]["item"] == "Цемент М400"
    assert result["top_items"][0]["quantity"] == "13"
    assert result["top_customers"][0]["counterparty"] == "ТОО Альфа Строй"
    assert result["top_customers"][0]["sales_amount"] == "400000"


def test_get_sales_document_details_formats_business_header_and_accounting_view():
    client = FakeOneCODataClient()

    detailed_raw = {
        "Ref_Key": "00000000-0000-0000-0000-000000000100",
        "Дата": "2026-04-20T12:00:00",
        "Date": "2026-04-20T12:00:00",
        "Контрагент": "ТОО Альфа Строй",
        "СуммаДокумента": "100000",
        "Номер": "000500",
        "Posted": True,
        "ДатаПодписанияАкта": "2026-04-21T00:00:00",
        "СпособВыпискиАктовВыполненныхРабот": "ВБумажномВиде",
        "ВидОперации": "РеализацияТоваровУслуг",
        "СтруктурноеПодразделение_Key": "dep-guid",
        "Ответственный_Key": "user-guid",
        "СчетНаОплатуПокупателю_Key": "11111111-1111-1111-1111-111111111111",
        "ДокументОснование": "22222222-2222-2222-2222-222222222222",
        "ДокументОснование_Type": "StandardODATA.Document_СчетНаОплатуПокупателю",
        "ДокументРасчетовСКонтрагентом": "33333333-3333-3333-3333-333333333333",
        "ДокументРасчетовСКонтрагентом_Type": "StandardODATA.Document_СчетНаОплатуПокупателю",
        "Товары": [
            {
                "Содержание": "Цемент М400",
                "Количество": 8,
                "Цена": 10000,
                "Сумма": "80000",
                "СчетУчетаБУ_Key": "acc-guid-1",
                "СчетДоходовБУ_Key": "acc-guid-2",
                "СчетСписанияСебестоимостиБУ_Key": "acc-guid-3",
                "СубконтоДоходовБУ1": "sub-guid-1",
                "СубконтоДоходовБУ1_Type": "StandardODATA.Catalog_Доходы",
                "СубконтоДоходовБУ2": "sub-guid-2",
                "СубконтоДоходовБУ2_Type": "StandardODATA.Catalog_НоменклатурныеГруппы",
                "СубконтоСписанияСебестоимостиБУ1": "sub-guid-3",
                "СубконтоСписанияСебестоимостиБУ1_Type": "StandardODATA.Catalog_СтатьиЗатрат",
            }
        ],
    }

    client._fetch_raw_entity_by_ref = lambda entity_name, ref_key: detailed_raw  # type: ignore[method-assign]
    original_resolve_reference_value = client._resolve_reference_value
    client._resolve_reference_value = lambda field_name, value: {  # type: ignore[method-assign]
        ("СтруктурноеПодразделение_Key", "dep-guid"): "Основное подразделение",
        ("Ответственный_Key", "user-guid"): "Сапар",
    }.get((field_name, value), original_resolve_reference_value(field_name, value))
    client._resolve_document_reference_display = lambda entity_name, ref_key: {  # type: ignore[method-assign]
        "11111111-1111-1111-1111-111111111111": "0000000127 от 2026-04-20",
        "22222222-2222-2222-2222-222222222222": "0000000127 от 2026-04-20",
        "33333333-3333-3333-3333-333333333333": "0000000127 от 2026-04-20",
    }.get(ref_key)
    client._resolve_account_field = lambda value: {  # type: ignore[method-assign]
        "acc-guid-1": "1330 Товары",
        "acc-guid-2": "6010 Доходы",
        "acc-guid-3": "7010 Себестоимость",
    }.get(value)
    client._resolve_typed_reference_display = lambda value, type_name: {  # type: ignore[method-assign]
        "sub-guid-1": "Доходы",
        "sub-guid-2": "Основная номенклатурная группа",
        "sub-guid-3": "Статьи затрат",
    }.get(value)

    result = client.get_sales_document_details(document_number="000500", max_lines=20)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["issue_method_display"] == "В бумажном виде"
    assert row["operation_type_display"] == "Реализация (Товары)"
    assert row["structural_unit"] == "Основное подразделение"
    assert row["responsible"] == "Сапар"
    assert row["invoice_document"] == "0000000127 от 2026-04-20"
    assert row["basis_document"] == "0000000127 от 2026-04-20"
    assert row["settlement_document"] == "0000000127 от 2026-04-20"
    assert row["document_link_mode"] == "direct_invoice_link"
    line = row["lines"][0]
    assert line["section_display"] == "ТМЗ"
    assert line["account_bu"] == "1330 Товары"
    assert line["account_bu_inferred_label"] is None
    assert line["account_bu_display"] == "1330 Товары"
    assert line["revenue_account_bu"] == "6010 Доходы"
    assert line["cogs_account_bu"] == "7010 Себестоимость"
    assert line["revenue_analytics_bu"] == ["Доходы", "Основная номенклатурная группа"]
    assert line["cogs_analytics_bu"] == ["Статьи затрат"]
    assert line["revenue_analytics_summary"] == "Доходы / Основная номенклатурная группа"
    assert line["cogs_analytics_summary"] == "Статьи затрат"
    assert line["accounting_view"]["revenue_account_bu"] == "6010 Доходы"
    assert line["accounting_view"]["revenue_account_bu_display"] == "6010 Доходы"


def test_get_sales_document_details_falls_back_to_basis_invoice_and_organization_for_zero_guid_structural_unit():
    client = FakeOneCODataClient()

    detailed_raw = {
        "Ref_Key": "00000000-0000-0000-0000-000000000101",
        "Дата": "2026-04-20T12:00:00",
        "Date": "2026-04-20T12:00:00",
        "Контрагент": "ТОО Альфа Строй",
        "СуммаДокумента": "100000",
        "Номер": "000501",
        "Организация": "ИП Isatay",
        "Posted": True,
        "ДатаПодписанияАкта": "2026-04-21T00:00:00",
        "СпособВыпискиАктовВыполненныхРабот": "ВБумажномВиде",
        "ВидОперации": "ПродажаКомиссия",
        "СтруктурноеПодразделение_Key": "00000000-0000-0000-0000-000000000000",
        "Ответственный_Key": "user-guid",
        "ДокументОснование": "22222222-2222-2222-2222-222222222222",
        "ДокументОснование_Type": "StandardODATA.Document_СчетНаОплатуПокупателю",
        "Товары": [{"Содержание": "Цемент М400", "Количество": 8, "Цена": 10000, "Сумма": "80000"}],
    }

    client._fetch_raw_entity_by_ref = lambda entity_name, ref_key: detailed_raw  # type: ignore[method-assign]
    client._resolve_reference_value = lambda field_name, value: "Сапар" if (field_name, value) == ("Ответственный_Key", "user-guid") else value  # type: ignore[method-assign]
    client._resolve_document_reference_display = lambda entity_name, ref_key: "0000000127 от 2026-04-20" if ref_key == "22222222-2222-2222-2222-222222222222" else None  # type: ignore[method-assign]
    client._fetch_entity_by_ref = lambda entity_name, ref_key, select_fields: {"Number": "0000000127", "Date": "2026-04-20T00:00:00"} if ref_key == "22222222-2222-2222-2222-222222222222" else None  # type: ignore[method-assign]

    result = client.get_sales_document_details(document_number="000501", max_lines=20)

    row = result["data"][0]
    assert row["structural_unit"] == "ИП Isatay"
    assert row["invoice_number"] == "0000000127"
    assert row["invoice_document"] == "0000000127 от 2026-04-20"
    assert row["basis_document"] == "0000000127 от 2026-04-20"
    assert row["document_link_mode"] == "basis_invoice_link"
    assert row["operation_type_display"] == "Реализация (Товары)"


def test_sales_line_accounting_view_uses_inferred_labels_as_display_fallback():
    client = FakeOneCODataClient()

    detailed_raw = {
        "Ref_Key": "00000000-0000-0000-0000-000000000102",
        "Дата": "2026-04-20T12:00:00",
        "Date": "2026-04-20T12:00:00",
        "Контрагент": "ТОО Альфа Строй",
        "СуммаДокумента": "100000",
        "Номер": "000503",
        "Posted": True,
        "ВидОперации": "ПродажаКомиссия",
        "Товары": [
            {
                "Содержание": "Цемент М400",
                "Количество": 8,
                "Цена": 10000,
                "Сумма": "80000",
                "СчетУчетаБУ_Key": "acc-guid-1",
                "СчетДоходовБУ_Key": "acc-guid-2",
                "СчетСписанияСебестоимостиБУ_Key": "acc-guid-3",
            }
        ],
    }

    client._fetch_raw_entity_by_ref = lambda entity_name, ref_key: detailed_raw  # type: ignore[method-assign]
    client._get_recent_sales_headers = lambda **kwargs: [{"number": "000503", "reference": detailed_raw["Ref_Key"]}]  # type: ignore[method-assign]
    client._resolve_account_field = lambda value: None  # type: ignore[method-assign]
    client._infer_account_label = lambda ref_key: {  # type: ignore[method-assign]
        "acc-guid-1": "Товары",
        "acc-guid-2": "Доход от реализации",
        "acc-guid-3": "Себестоимость реализации",
    }.get(ref_key)

    result = client.get_sales_document_details(document_number="000503", max_lines=20)

    line = result["data"][0]["lines"][0]
    assert line["account_bu"] is None
    assert line["account_bu_display"] == "Товары"
    assert line["revenue_account_bu_display"] == "Доход от реализации"
    assert line["cogs_account_bu_display"] == "Себестоимость реализации"


def test_sales_document_link_mode_reports_comment_only_and_no_links():
    client = FakeOneCODataClient()

    assert client._extract_sales_document_link_mode({"Комментарий": "КАРТА от 05.05.2026"}) == "comment_only"
    assert client._extract_sales_document_link_mode({}) == "no_linked_documents"


def test_infer_account_labels_from_correspondence_catalog():
    client = FakeOneCODataClient()
    original_query = client.query_entity

    def patched_query(entity_name, top=50, select=None, filter_expr=None, orderby=None, skip=0):
        if entity_name == "Catalog_КорреспонденцииСчетов":
            return {
                "entity": entity_name,
                "count_returned": 3,
                "top_applied": top,
                "data": [
                    {
                        "СчетДт_Key": "8a906a7e-7eb2-11ee-a060-e0d55e49a969",
                        "СчетКт_Key": "8a90697a-7eb2-11ee-a060-e0d55e49a969",
                        "ТипДокумента": "Реализация ТМЗ и услуг",
                        "ВидОперацииДокумента": "Реализация",
                        "Содержание": "Реализация товаров",
                    },
                    {
                        "СчетДт_Key": "00000000-0000-0000-0000-000000000000",
                        "СчетКт_Key": "8a906a64-7eb2-11ee-a060-e0d55e49a969",
                        "ТипДокумента": "Реализация ТМЗ и услуг",
                        "ВидОперацииДокумента": "Реализация",
                        "Содержание": "Реализация готовой продукции, товаров на договорную стоимость",
                    },
                    {
                        "СчетДт_Key": "8a90697a-7eb2-11ee-a060-e0d55e49a969",
                        "СчетКт_Key": "00000000-0000-0000-0000-000000000000",
                        "ТипДокумента": "Поступление ТМЗ и услуг",
                        "ВидОперацииДокумента": "Покупка",
                        "Содержание": "Приобретение товаров: у физических лиц и организаций",
                    },
                ],
            }
        return original_query(entity_name, top=top, select=select, filter_expr=filter_expr, orderby=orderby, skip=skip)

    client.query_entity = patched_query  # type: ignore[method-assign]

    assert client._infer_account_label("8a90697a-7eb2-11ee-a060-e0d55e49a969") == "Товары"
    assert client._infer_account_label("8a906a64-7eb2-11ee-a060-e0d55e49a969") == "Доход от реализации"
    assert client._infer_account_label("8a906a7e-7eb2-11ee-a060-e0d55e49a969") == "Себестоимость реализации"


def test_get_sales_documents_uses_tail_paging_when_filter_pushdown_is_rejected():
    client = FakeOneCODataClientSalesTailPaging()

    result = client.get_sales_documents(date_from="2026-05-01", date_to="2026-05-31", limit=10)

    assert result["count_returned"] == 2
    assert result["data"][0]["number"] == "0000001288"
    assert result["data"][1]["number"] == "0000001287"
    assert result["source_entities_used"] == ["Document_РеализацияТоваровУслуг"]
    assert any(query["skip"] == 250 for query in client.captured_queries)


def test_get_purchase_documents_combines_supplier_sources_and_returns_latest_rows_first():
    client = FakeOneCODataClientPurchaseTailPaging()

    result = client.get_purchase_documents(date_from="2026-05-01", date_to="2026-05-31", limit=10)

    assert result["count_returned"] == 2
    assert result["source_entities_used"] == ["Document_СчетФактураПолученный", "Document_ПоступлениеТоваровУслуг"]
    assert result["data"][0]["number"] == "0000000279"
    assert result["data"][1]["number"] == "0000000272"
    assert any(query["entity_name"] == "Document_СчетФактураПолученный" and query["skip"] >= 100 for query in client.captured_queries)
    assert any(query["entity_name"] == "Document_ПоступлениеТоваровУслуг" and query["skip"] >= 100 for query in client.captured_queries)


def test_search_document_by_number_falls_back_when_odata_filter_is_rejected():
    client = FakeOneCODataClientRejectingDocumentFilter()

    result = client.search_document_by_number(document_number="00050", document_type="Реализация", limit=5)

    assert result["count_returned"] == 3
    assert result["data"][0]["number"] == "000502"
    assert any("rejected pushdown filter" in warning for warning in result["warnings"])
    assert client.captured_queries[0]["entity_name"] == "Document_РеализацияТоваровУслуг"
    assert client.captured_queries[0]["filter_expr"] is None
    assert any(query["skip"] > 0 for query in client.captured_queries)


def test_search_document_by_number_finds_supplier_document_via_tail_paging_when_filter_rejected():
    client = FakeOneCODataClientPurchaseTailPaging()

    result = client.search_document_by_number(document_number="0279", document_type="Счет-фактура", limit=5)

    assert result["count_returned"] == 1
    assert result["data"][0]["document_type"] == "Document_СчетФактураПолученный"
    assert result["data"][0]["number"] == "0000000279"
    assert result["data"][0]["counterparty"] == "Жакко Караганда"
    assert any(query["entity_name"] == "Document_СчетФактураПолученный" and query["skip"] >= 100 for query in client.captured_queries)


def test_search_document_by_number_limits_candidate_scan_for_large_bases():
    client = FakeOneCODataClient()

    original = client._discover_document_search_candidates
    captured = {}

    def wrapped(document_type=None, limit=None):
        captured["document_type"] = document_type
        captured["limit"] = limit
        return original(document_type=document_type, limit=limit)

    client._discover_document_search_candidates = wrapped  # type: ignore[method-assign]

    result = client.search_document_by_number(document_number="00050", limit=5)

    assert result["count_returned"] == 3
    assert captured["document_type"] is None
    assert captured["limit"] == 10


def test_search_document_by_number_rejects_invalid_date_range():
    client = FakeOneCODataClient()

    try:
        client.search_document_by_number(document_number="00050", date_from="2026-05-01", date_to="2026-04-01", limit=5)
        assert False, "Expected ODataError for invalid date range"
    except Exception as exc:
        assert "date_from" in str(exc)


def test_search_document_by_number_skips_entity_when_fallback_read_is_forbidden():
    client = FakeOneCODataClientRejectingDocumentFilterAndFallbackAccess()

    result = client.search_document_by_number(document_number="00050", document_type="Реализация", limit=5)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert any("not accessible for this entity" in warning for warning in result["warnings"])


def test_search_document_by_number_prefers_purchase_documents_for_postuplenie_hint():
    client = FakeOneCODataClientAmbiguousReceiptNumber()

    result = client.search_document_by_number(document_number="0247", document_type="Поступление", limit=10)

    assert result["count_returned"] == 1
    assert result["data"][0]["document_type"] == "Document_ПоступлениеТоваровУслуг"
    assert result["data"][0]["number"] == "0000000247"


def test_setup_wizard_does_not_return_raw_odata_url_in_checks():
    client = FakeOneCODataClient()

    result = client.setup_wizard(check_live_entities=False, live_limit=5)

    url_check = next(check for check in result["checks"] if check["name"] == "ONEC_ODATA_URL configured")
    assert url_check["details"] == "configured"
    assert "http://" not in str(url_check["details"])


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


def test_generate_database_profile_returns_partial_profile_when_candidate_discovery_fails():
    client = FakeOneCODataClient()
    client.discover_payment_sources = lambda limit=10, check_data=True: (_ for _ in ()).throw(ODataError("timed out"))  # type: ignore[method-assign]

    result = client.generate_database_profile(check_inventory_data=True, live_limit=0)

    assert result["entity_summary"]["total"] > 0
    assert result["payment_candidates"] == []
    assert result["warnings"]
    assert any("payment_candidates" in warning for warning in result["warnings"])
    assert any("partial mode" in risk for risk in result["risks"])


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


def test_get_supplier_settlements_summary_returns_safe_payables_rows():
    client = FakeOneCODataClient()

    result = client.get_supplier_settlements_summary(date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 2
    assert result["data"][0]["counterparty"] == "ТОО Cement Trade"
    assert result["data"][0]["debt_amount"] == "110000"
    assert result["data"][0]["last_payment_date"] == "2026-04-25"
    assert result["data"][0]["overdue_days"] == 10
    assert result["data"][0]["source_document_count"] == 2
    assert result["data"][0]["source_entity"] == "Document_ПоступлениеТоваровУслуг"
    assert result["data"][0]["currency"] is None
    assert result["source_explanation"]["purchase_documents_used"] == "Document_ПоступлениеТоваровУслуг"
    assert result["source_explanation"]["outgoing_payments_used"] == "Document_СписаниеСБанковскогоСчета"
    assert "официальным бухгалтерским актом сверки" in result["note"]


def test_get_supplier_settlements_summary_caps_limit_and_min_debt():
    client = FakeOneCODataClient()

    result = client.get_supplier_settlements_summary(date_to="2026-04-30", min_debt="70000", limit=100)

    assert result["count_returned"] == 1
    assert result["filters_applied_in_python"]["limit"] == 50
    assert result["data"][0]["counterparty"] == "ТОО Cement Trade"


def test_get_supplier_settlements_summary_handles_missing_sources_gracefully():
    client = FakeOneCODataClient()
    client.discover_purchase_sources = lambda limit=1, check_data=True: []  # type: ignore[method-assign]

    result = client.get_supplier_settlements_summary(date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert "purchase_documents" in result["missing_sources"]
    assert result["warnings"]
    assert result["source_explanation"]["basis"] == "summary_not_built"


def test_get_supplier_settlements_summary_rejects_invalid_min_debt():
    client = FakeOneCODataClient()

    try:
        client.get_supplier_settlements_summary(date_to="2026-04-30", min_debt="not-a-number")
        assert False, "Expected ODataError for invalid min_debt"
    except Exception as exc:
        assert "min_debt" in str(exc)


def test_get_supplier_debt_document_breakdown_returns_document_reasons():
    client = FakeOneCODataClient()

    result = client.get_supplier_debt_document_breakdown(date_to="2026-04-30", limit=5, documents_per_supplier=3)

    assert result["count_returned"] == 2
    top = result["data"][0]
    assert top["counterparty"] == "ТОО Cement Trade"
    assert top["documents"][0]["document_number"] == "SUP-001"
    assert top["documents"][0]["outstanding_amount"] == "70000"
    assert top["documents"][0]["paid_amount_estimate"] == "50000"
    assert top["documents"][0]["section_counts"]["goods"] == 2
    assert top["documents"][0]["line_items_sample"][0]["name"] == "Цемент М400"
    assert top["documents"][1]["section_counts"]["services"] == 1


def test_get_supplier_debt_document_breakdown_handles_missing_sources_gracefully():
    client = FakeOneCODataClient()
    client.discover_purchase_sources = lambda limit=1, check_data=True: []  # type: ignore[method-assign]

    result = client.get_supplier_debt_document_breakdown(date_to="2026-04-30", limit=5)

    assert result["count_returned"] == 0
    assert result["data"] == []
    assert "purchase_documents" in result["missing_sources"]


def test_get_supplier_reconciliation_documents_returns_published_act_rows():
    client = FakeOneCODataClient()

    result = client.get_supplier_reconciliation_documents(date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 1
    row = result["data"][0]
    assert row["counterparty"] == "ТОО Cement Trade"
    assert row["reconciliation_number"] == "SV-001"
    assert row["purchase_document_count"] == 2
    assert row["outgoing_payment_count"] == 1
    assert row["purchase_amount_total"] == "160000"
    assert row["outgoing_payment_amount_total"] == "50000"
    assert row["balance_estimate_by_organization_view"] == "130000"
    assert row["source_entity"] == "Document_АктСверкиВзаиморасчетов"
    assert row["organization_view_lines_sample"][0]["document_type"] == "StandardODATA.Document_ПоступлениеТоваровУслуг"
    assert result["source_explanation"]["basis"] == "published_reconciliation_documents_from_1c"


def test_get_supplier_reconciliation_documents_filters_by_counterparty_and_caps_limit():
    client = FakeOneCODataClient()

    result = client.get_supplier_reconciliation_documents(
        date_to="2026-04-30",
        counterparty_name="Cement Trade",
        limit=100,
        lines_per_document=100,
    )

    assert result["count_returned"] == 1
    assert result["filters_applied_in_python"]["limit"] == 20
    assert result["filters_applied_in_python"]["lines_per_document"] == 10


def test_get_supplier_reconciliation_documents_handles_missing_source_gracefully():
    client = FakeOneCODataClient()
    client._entities_cache = [entity for entity in client.list_entities() if entity.name != "Document_АктСверкиВзаиморасчетов"]

    result = client.get_supplier_reconciliation_documents(date_to="2026-04-30", limit=10)

    assert result["count_returned"] == 0
    assert "supplier_reconciliation_documents" in result["missing_sources"]
    assert result["source_explanation"]["basis"] == "source_missing"


def test_get_supplier_reconciliation_documents_rejects_invalid_date_range():
    client = FakeOneCODataClient()

    try:
        client.get_supplier_reconciliation_documents(date_from="2026-05-01", date_to="2026-04-01")
        assert False, "Expected ODataError for invalid date range"
    except Exception as exc:
        assert "date_from" in str(exc)


def test_get_procurement_recommendations_uses_sales_30_days_and_current_stock():
    client = FakeOneCODataClient()

    result = client.get_procurement_recommendations(days=30, as_of_date="2026-04-30", limit=10)

    assert result["count_returned"] >= 2
    top = result["data"][0]
    assert top["item"] == "Цемент М400"
    assert top["sold_quantity_last_days"] == "13"
    assert top["current_stock"] == "3"
    assert top["recommended_purchase_qty"] == "10"
    assert top["sales_document_count"] == 2
    assert top["preferred_supplier"] == "ТОО Cement Trade"
    assert top["supplier_last_purchase_document_number"] == "SUP-001"
    assert top["supplier_match_method"] == "exact_item_name"
    assert top["supplier_match_confidence"] == "high"
    assert top["supplier_candidates"][0]["supplier"] == "ТОО Cement Trade"
    assert top["supplier_candidates"][0]["match_method"] == "exact_item_name"
    assert result["source_explanation"]["basis"] == "recent_sales_and_current_stock"
    assert result["source_explanation"]["purchase_source"] == "Document_ПоступлениеТоваровУслуг"


def test_get_procurement_recommendations_caps_limit_and_infers_as_of():
    client = FakeOneCODataClient()

    result = client.get_procurement_recommendations(limit=100)

    assert result["filters_applied_in_python"]["limit"] == 30
    assert result["filters_applied_in_python"]["as_of_date"] == "2026-04-24"


def test_get_procurement_recommendations_rejects_invalid_as_of_date():
    client = FakeOneCODataClient()

    try:
        client.get_procurement_recommendations(as_of_date="not-a-date")
        assert False, "Expected ODataError for invalid as_of_date"
    except Exception as exc:
        assert "as_of_date" in str(exc)


def test_get_procurement_recommendations_does_not_fabricate_supplier_when_purchase_history_missing():
    client = FakeOneCODataClient()

    result = client.get_procurement_recommendations(days=30, as_of_date="2026-04-30", limit=10)

    bokorez = next(row for row in result["data"] if row["item"] == "Бокорез")
    assert bokorez["preferred_supplier"] is None
    assert bokorez["supplier_last_purchase_date"] is None
    assert bokorez["supplier_last_purchase_document_number"] is None
    assert bokorez["supplier_match_method"] is None
    assert bokorez["supplier_match_confidence"] is None
    assert bokorez["supplier_candidates"] == []


def test_get_procurement_recommendations_fast_uses_sales_rows_and_stock_snapshot():
    client = FakeOneCODataClient()

    result = client.get_procurement_recommendations_fast(days=5, as_of_date="2026-04-24", limit=10)

    assert result["count_returned"] >= 2
    top = result["data"][0]
    assert top["item"] == "Цемент М400"
    assert top["sold_quantity_last_days"] == "13"
    assert top["current_stock"] == "3"
    assert top["recommended_purchase_qty"] == "10"
    assert top["sales_document_count"] == 2
    assert top["sales_row_source"] == "Document_РеализацияТоваровУслуг_Товары"
    assert result["source_explanation"]["basis"] == "recent_sales_row_tail_and_virtual_current_stock"


def test_get_procurement_recommendations_fast_caps_limit_and_infers_as_of():
    client = FakeOneCODataClient()

    result = client.get_procurement_recommendations_fast(limit=100)

    assert result["filters_applied_in_python"]["limit"] == 30
    assert result["filters_applied_in_python"]["as_of_date"] == "2026-04-24"


def test_get_material_statement_view_reconstructs_1330_opening_turnovers_and_closing():
    client = FakeOneCODataClient()

    result = client.get_material_statement_view(date_from="2026-05-01", date_to="2026-05-31", limit=50)

    assert result["account"]["requested"] == "1330"
    assert result["totals"]["opening_qty"] == "8"
    assert result["totals"]["opening_amount"] == "800"
    assert result["totals"]["incoming_qty"] == "6"
    assert result["totals"]["incoming_amount"] == "1000"
    assert result["totals"]["outgoing_qty"] == "7"
    assert result["totals"]["outgoing_amount"] == "800"
    assert result["totals"]["closing_qty"] == "7"
    assert result["totals"]["closing_amount"] == "1000"
    assert result["source_breakdown"]["3310"]["incoming_amount"] == "200"
    assert result["source_breakdown"]["7000"]["incoming_amount"] == "200"
    assert result["source_breakdown"]["7000"]["outgoing_amount"] == "200"
    assert result["source_breakdown"]["1330"]["incoming_amount"] == "600"
    assert result["source_breakdown"]["1330"]["outgoing_amount"] == "600"

    rows = {(row["item_ref"], row["warehouse_ref"]): row for row in result["data"]}
    assert rows[("10000000-0000-0000-0000-000000000001", "20000000-0000-0000-0000-000000000001")]["opening_qty"] == "8"
    assert rows[("10000000-0000-0000-0000-000000000001", "20000000-0000-0000-0000-000000000001")]["outgoing_qty"] == "6"
    assert rows[("10000000-0000-0000-0000-000000000001", "20000000-0000-0000-0000-000000000001")]["closing_qty"] == "2"
    assert rows[("10000000-0000-0000-0000-000000000001", None)]["opening_qty"] == "0"
    assert rows[("10000000-0000-0000-0000-000000000001", None)]["incoming_qty"] == "2"
    assert rows[("10000000-0000-0000-0000-000000000001", None)]["closing_qty"] == "2"
    assert rows[("10000000-0000-0000-0000-000000000002", "20000000-0000-0000-0000-000000000001")]["incoming_qty"] == "1"
    assert rows[("10000000-0000-0000-0000-000000000002", "20000000-0000-0000-0000-000000000001")]["closing_amount"] == "200"
    assert rows[("10000000-0000-0000-0000-000000000003", "20000000-0000-0000-0000-000000000001")]["opening_amount"] == "0"
    assert rows[("10000000-0000-0000-0000-000000000003", "20000000-0000-0000-0000-000000000001")]["incoming_qty"] == "3"
    assert rows[("10000000-0000-0000-0000-000000000003", "20000000-0000-0000-0000-000000000001")]["outgoing_qty"] == "1"
    assert rows[("10000000-0000-0000-0000-000000000003", "20000000-0000-0000-0000-000000000001")]["closing_qty"] == "2"


def test_get_material_statement_view_falls_back_when_material_filters_return_http_500():
    client = FakeOneCODataClientMaterialFilterFallback()

    result = client.get_material_statement_view(date_from="2026-05-01", date_to="2026-05-31", limit=50)

    assert result["totals"]["opening_amount"] == "800"
    assert result["totals"]["incoming_amount"] == "1000"
    assert result["totals"]["outgoing_amount"] == "800"
    assert any("Pushdown filter for Document_ПоступлениеТоваровУслуг failed" in warning for warning in result["warnings"])
    assert any("Pushdown filter for AccumulationRegister_РеализацияТМЗ_RecordType failed" in warning for warning in result["warnings"])
    assert any("Pushdown filter for Document_КомплектацияНоменклатуры failed" in warning for warning in result["warnings"])


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
    assert "incoming_sources_checked" in result["source_explanation"]
    assert "outgoing_sources_checked" in result["source_explanation"]


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
