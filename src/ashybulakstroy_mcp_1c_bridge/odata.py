from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-zА-Яа-я0-9_\.]+$")


class ODataError(RuntimeError):
    pass


@dataclass(frozen=True)
class FieldInfo:
    name: str
    type: str | None = None
    nullable: bool | None = None


@dataclass(frozen=True)
class EntityInfo:
    name: str
    entity_type: str | None = None
    fields: list[FieldInfo] | None = None


class OneCODataClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        auth = None
        if settings.username and settings.password:
            auth = (settings.username, settings.password)
        self.client = httpx.Client(
            timeout=settings.timeout_seconds,
            verify=settings.verify_ssl,
            auth=auth,
            headers={"Accept": "application/json"},
        )
        self._metadata_xml: str | None = None
        self._entities_cache: list[EntityInfo] | None = None

    def _require_url(self) -> None:
        if not self.settings.odata_url:
            raise ODataError("ONEC_ODATA_URL не задан. Заполните .env или переменные окружения.")

    def _url(self, path: str) -> str:
        self._require_url()
        return f"{self.settings.odata_url}/{path.lstrip('/')}"

    def get_metadata_xml(self, refresh: bool = False) -> str:
        if self._metadata_xml is not None and not refresh:
            return self._metadata_xml
        response = self.client.get(self._url("$metadata"), headers={"Accept": "application/xml"})
        if response.status_code >= 400:
            raise ODataError(f"Ошибка чтения $metadata: HTTP {response.status_code}: {response.text[:500]}")
        self._metadata_xml = response.text
        self._entities_cache = None
        return self._metadata_xml

    def list_entities(self, refresh: bool = False) -> list[EntityInfo]:
        if self._entities_cache is not None and not refresh:
            return self._entities_cache

        xml = self.get_metadata_xml(refresh=refresh)
        root = ET.fromstring(xml)
        ns = {
            "edmx": "http://schemas.microsoft.com/ado/2007/06/edmx",
            "edm": "http://schemas.microsoft.com/ado/2008/09/edm",
        }
        entity_types: dict[str, list[FieldInfo]] = {}
        for et in root.findall(".//edm:EntityType", ns):
            et_name = et.attrib.get("Name")
            if not et_name:
                continue
            fields: list[FieldInfo] = []
            for prop in et.findall("edm:Property", ns):
                fields.append(
                    FieldInfo(
                        name=prop.attrib.get("Name", ""),
                        type=prop.attrib.get("Type"),
                        nullable=(prop.attrib.get("Nullable", "true").lower() != "false"),
                    )
                )
            entity_types[et_name] = fields

        entities: list[EntityInfo] = []
        for container in root.findall(".//edm:EntityContainer", ns):
            for entity_set in container.findall("edm:EntitySet", ns):
                name = entity_set.attrib.get("Name")
                raw_type = entity_set.attrib.get("EntityType")
                short_type = raw_type.split(".")[-1] if raw_type else None
                if name:
                    entities.append(
                        EntityInfo(
                            name=name,
                            entity_type=short_type,
                            fields=entity_types.get(short_type or "", []),
                        )
                    )
        self._entities_cache = sorted(entities, key=lambda e: e.name)
        return self._entities_cache

    def describe_entity(self, entity_name: str) -> EntityInfo | None:
        for entity in self.list_entities():
            if entity.name == entity_name:
                return entity
        return None

    def sample_entity(self, entity_name: str, top: int = 5) -> dict[str, Any]:
        return self.query_entity(entity_name=entity_name, top=top)

    def query_entity(
        self,
        entity_name: str,
        top: int = 50,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        skip: int = 0,
    ) -> dict[str, Any]:
        self._validate_identifier(entity_name, "entity_name")
        top = min(max(int(top), 1), self.settings.max_top)
        params: dict[str, Any] = {"$top": top}
        if skip > 0:
            params["$skip"] = int(skip)
        if select:
            for field in select:
                self._validate_identifier(field, "select field")
            params["$select"] = ",".join(select)
        if filter_expr:
            params["$filter"] = filter_expr
        if orderby:
            params["$orderby"] = orderby

        response = self.client.get(self._url(entity_name), params=params)
        if response.status_code >= 400:
            raise ODataError(f"Ошибка OData запроса: HTTP {response.status_code}: {response.text[:1000]}")
        data = response.json()
        values = data.get("value", data if isinstance(data, list) else [])
        return {
            "entity": entity_name,
            "count_returned": len(values) if isinstance(values, list) else None,
            "top_applied": top,
            "data": values,
        }

    def search_metadata(self, text: str, limit: int = 30) -> list[dict[str, Any]]:
        q = text.strip().lower()
        if not q:
            return []
        out: list[dict[str, Any]] = []
        for e in self.list_entities():
            score = 0
            if q in e.name.lower():
                score += 10
            matches = []
            for f in e.fields or []:
                if q in f.name.lower() or (f.type and q in f.type.lower()):
                    matches.append({"name": f.name, "type": f.type})
                    score += 2
            if score:
                out.append({"entity": e.name, "entity_type": e.entity_type, "score": score, "fields": matches[:20]})
        return sorted(out, key=lambda r: r["score"], reverse=True)[:limit]

    def explore_live_entities(self, limit: int = 200) -> list[dict[str, Any]]:
        result = []
        for entity in self.list_entities()[:limit]:
            try:
                sample = self.query_entity(entity.name, top=1)
                live = bool(sample.get("data"))
                result.append({"entity": entity.name, "has_data": live, "sample_count": sample.get("count_returned")})
            except Exception as exc:
                result.append({"entity": entity.name, "has_data": None, "error": str(exc)[:300]})
        return result

    def discover_inventory_sources(self, limit: int = 10, check_data: bool = True) -> list[dict[str, Any]]:
        """Find likely inventory/stock OData entities using metadata heuristics."""
        candidates: list[dict[str, Any]] = []
        for entity in self.list_entities():
            score, reasons = self._score_inventory_entity(entity)
            if score <= 0:
                continue
            fields = entity.fields or []
            field_names = [f.name for f in fields]
            mapped = self._map_inventory_fields(field_names)
            row: dict[str, Any] = {
                "entity": entity.name,
                "entity_type": entity.entity_type,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
                "field_count": len(field_names),
                "sample_fields": field_names[:40],
            }
            if check_data:
                try:
                    sample = self.query_entity(entity.name, top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 10
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
            candidates.append(row)
        return sorted(candidates, key=lambda r: r["score"], reverse=True)[:limit]

    def get_inventory_auto(
        self,
        warehouse: str | None = None,
        item: str | None = None,
        limit: int = 50,
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Read inventory-like rows from the best metadata candidate.

        This is intentionally adaptive: it does not assume exact 1C endpoint names.
        Text filters are applied in Python to avoid generating unsafe or wrong OData filters
        against unknown customized configurations.
        """
        if entity_name:
            entity = self.describe_entity(entity_name)
            if entity is None:
                raise ODataError(f"Сущность не найдена: {entity_name}")
            score, reasons = self._score_inventory_entity(entity)
            mapped = self._map_inventory_fields([f.name for f in (entity.fields or [])])
            source = {
                "entity": entity.name,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
            }
        else:
            sources = self.discover_inventory_sources(limit=1, check_data=True)
            if not sources:
                raise ODataError("Не найден кандидат на источник остатков. Запустите discover_inventory_sources для диагностики.")
            source = sources[0]

        mapped = source.get("mapped_fields") or {}
        select = self._build_inventory_select(mapped)
        raw = self.query_entity(source["entity"], top=min(limit * 3, self.settings.max_top), select=select or None)
        rows = raw.get("data") or []
        normalized = [self._normalize_inventory_row(r, mapped) for r in rows]

        warnings: list[str] = []
        if warehouse:
            normalized = [r for r in normalized if self._text_match(r.get("warehouse"), warehouse) or self._text_match(r.get("raw"), warehouse)]
        if item:
            normalized = [r for r in normalized if self._text_match(r.get("item"), item) or self._text_match(r.get("raw"), item)]
        if not mapped.get("quantity"):
            warnings.append("Не найдено явное поле количества. Проверьте mapped_fields и источник вручную.")
        if not mapped.get("item"):
            warnings.append("Не найдено явное поле номенклатуры. Возможна техническая ссылка вместо названия.")
        if not mapped.get("warehouse"):
            warnings.append("Не найдено явное поле склада. Возможно, источник не разделяет остатки по складам.")

        return {
            "source": source,
            "filters_applied_in_python": {"warehouse": warehouse, "item": item},
            "count_returned": min(len(normalized), limit),
            "data": normalized[:limit],
            "warnings": warnings,
            "note": "Автоопределение основано на metadata и sample OData. Для бухгалтерской точности подтвердите источник и сохраните verified recipe.",
        }

    def get_low_stock_items(
        self,
        warehouse: str | None = None,
        item: str | None = None,
        threshold_quantity: str | int | float | Decimal = "10",
        limit: int = 50,
        entity_name: str | None = None,
        include_zero: bool = True,
    ) -> dict[str, Any]:
        """Return items with low stock based on current adaptive inventory source."""
        threshold = self._to_decimal(threshold_quantity)
        inventory = self.get_inventory_auto(
            warehouse=warehouse,
            item=item,
            limit=min(max(limit * 5, 50), self.settings.max_top),
            entity_name=entity_name,
        )
        rows = inventory.get("data") or []
        low: list[dict[str, Any]] = []
        skipped_without_quantity = 0

        for row in rows:
            qty = self._to_decimal(row.get("quantity"), default=None)
            if qty is None:
                skipped_without_quantity += 1
                continue
            if qty <= threshold and (include_zero or qty != 0):
                severity = "critical" if qty <= 0 else "high"
                low.append({
                    "item": row.get("item"),
                    "warehouse": row.get("warehouse"),
                    "quantity": str(qty.normalize()) if qty == qty.to_integral() else str(qty),
                    "amount": row.get("amount"),
                    "period": row.get("period"),
                    "severity": severity,
                    "reason": f"quantity <= threshold ({threshold})",
                    "raw": row.get("raw"),
                })

        low.sort(key=lambda r: (self._severity_rank(r.get("severity")), self._to_decimal(r.get("quantity"), default=Decimal("0"))))
        warnings = list(inventory.get("warnings") or [])
        if skipped_without_quantity:
            warnings.append(f"Пропущено строк без распознанного количества: {skipped_without_quantity}.")
        warnings.append("MVP-фича использует порог остатка, а не прогноз продаж. Для решения о закупке сверяйте источник с отчетом 1С.")

        return {
            "source": inventory.get("source"),
            "filters_applied_in_python": inventory.get("filters_applied_in_python"),
            "threshold_quantity": str(threshold),
            "count_low_stock": min(len(low), limit),
            "data": low[:limit],
            "warnings": warnings,
            "next_step": "Сверьте 3-5 критичных позиций через validate_inventory_report_text и затем настройте verified recipe.",
        }

    def discover_payment_sources(
        self,
        direction: str | None = None,
        limit: int = 10,
        check_data: bool = True,
    ) -> list[dict[str, Any]]:
        """Find likely incoming/outgoing payment entities using metadata heuristics."""
        normalized_direction = self._normalize_payment_direction(direction)
        candidates: list[dict[str, Any]] = []
        for entity in self.list_entities():
            score, reasons, entity_direction = self._score_payment_entity(entity)
            if score <= 0:
                continue
            if normalized_direction and entity_direction != normalized_direction:
                continue
            fields = entity.fields or []
            field_names = [f.name for f in fields]
            mapped = self._map_payment_fields(field_names)
            row: dict[str, Any] = {
                "entity": entity.name,
                "entity_type": entity.entity_type,
                "direction": entity_direction,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
                "field_count": len(field_names),
                "sample_fields": field_names[:40],
            }
            if check_data:
                try:
                    sample = self.query_entity(entity.name, top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 8
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
            candidates.append(row)
        return sorted(candidates, key=lambda r: r["score"], reverse=True)[:limit]

    def discover_sales_sources(
        self,
        limit: int = 10,
        check_data: bool = True,
    ) -> list[dict[str, Any]]:
        """Find likely sales/invoice entities using metadata heuristics."""
        candidates: list[dict[str, Any]] = []
        for entity in self.list_entities():
            score, reasons = self._score_sales_entity(entity)
            if score <= 0:
                continue
            fields = entity.fields or []
            field_names = [f.name for f in fields]
            mapped = self._map_sales_fields(field_names)
            row: dict[str, Any] = {
                "entity": entity.name,
                "entity_type": entity.entity_type,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
                "field_count": len(field_names),
                "sample_fields": field_names[:40],
            }
            if check_data:
                try:
                    sample = self.query_entity(entity.name, top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 8
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
            candidates.append(row)
        return sorted(candidates, key=lambda r: r["score"], reverse=True)[:limit]

    def get_sales_documents(
        self,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty: str | None = None,
        limit: int = 100,
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Read sales/invoice-like rows from OData using metadata heuristics."""
        if entity_name:
            entity = self.describe_entity(entity_name)
            if entity is None:
                raise ODataError(f"Сущность не найдена: {entity_name}")
            score, reasons = self._score_sales_entity(entity)
            mapped = self._map_sales_fields([f.name for f in (entity.fields or [])])
            source = {
                "entity": entity.name,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
            }
        else:
            sources = self.discover_sales_sources(limit=1, check_data=True)
            if not sources:
                raise ODataError("Не найден кандидат на источник реализаций/счетов. Запустите discover_sales_sources для диагностики.")
            source = sources[0]

        mapped = source.get("mapped_fields") or {}
        select = self._build_sales_select(mapped)
        raw = self.query_entity(source["entity"], top=min(limit * 5, self.settings.max_top), select=select or None)
        rows = raw.get("data") or []
        normalized = [self._normalize_sales_row(r, mapped) for r in rows]

        effective_from = date or date_from
        effective_to = date or date_to
        warnings: list[str] = []
        if effective_from or effective_to:
            normalized = [r for r in normalized if self._date_in_range(r.get("date"), effective_from, effective_to)]
        if counterparty:
            normalized = [r for r in normalized if self._text_match(r.get("counterparty"), counterparty) or self._text_match(r.get("raw"), counterparty)]
        if not mapped.get("counterparty"):
            warnings.append("Не найдено явное поле контрагента в источнике реализаций.")
        if not mapped.get("amount"):
            warnings.append("Не найдено явное поле суммы в источнике реализаций.")
        if not mapped.get("date"):
            warnings.append("Не найдено явное поле даты в источнике реализаций.")

        total_amount = Decimal("0")
        for row in normalized[:limit]:
            amount = self._to_decimal(row.get("amount"), default=None)
            if amount is not None:
                total_amount += amount

        return {
            "source": source,
            "filters_applied_in_python": {
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
                "counterparty": counterparty,
            },
            "count_returned": min(len(normalized), limit),
            "total_amount": str(total_amount),
            "data": normalized[:limit],
            "warnings": warnings,
            "note": "Реализации/счета определены по metadata-эвристике OData. Для точного дебиторского учета сверяйте с официальными отчетами 1С.",
        }

    def get_unpaid_customers_summary(
        self,
        date_to: str | None = None,
        date_from: str | None = None,
        counterparty: str | None = None,
        limit: int = 20,
        sales_entity_name: str | None = None,
        payment_entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Return customers with billed amounts exceeding received payments."""
        sales = self.get_sales_documents(
            date_from=date_from,
            date_to=date_to,
            counterparty=counterparty,
            limit=max(limit * 20, 200),
            entity_name=sales_entity_name,
        )
        incoming = self.get_payments(
            direction="incoming",
            date_from=date_from,
            date_to=date_to,
            counterparty=counterparty,
            limit=max(limit * 20, 200),
            entity_name=payment_entity_name,
        )

        sales_totals: dict[str, Decimal] = {}
        payment_totals: dict[str, Decimal] = {}
        sales_dates: dict[str, tuple[str | None, str | None]] = {}

        for row in sales.get("data") or []:
            name = str(row.get("counterparty") or "<unknown>")
            amount = self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0")
            sales_totals[name] = sales_totals.get(name, Decimal("0")) + amount
            row_date = self._parse_date_like(row.get("date"))
            if row_date:
                iso = row_date.isoformat()
                first, last = sales_dates.get(name, (None, None))
                if first is None or iso < first:
                    first = iso
                if last is None or iso > last:
                    last = iso
                sales_dates[name] = (first, last)

        for row in incoming.get("data") or []:
            name = str(row.get("counterparty") or "<unknown>")
            amount = self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0")
            payment_totals[name] = payment_totals.get(name, Decimal("0")) + amount

        rows: list[dict[str, Any]] = []
        for name, billed in sales_totals.items():
            paid = payment_totals.get(name, Decimal("0"))
            outstanding = billed - paid
            if outstanding > 0:
                first, last = sales_dates.get(name, (None, None))
                rows.append(
                    {
                        "counterparty": name,
                        "billed_amount": str(billed),
                        "paid_amount": str(paid),
                        "outstanding_amount": str(outstanding),
                        "first_sale_date": first,
                        "last_sale_date": last,
                    }
                )

        rows.sort(key=lambda x: self._to_decimal(x["outstanding_amount"], default=Decimal("0")), reverse=True)
        warnings = list(sales.get("warnings") or []) + list(incoming.get("warnings") or [])
        warnings.append("Это эвристическая оценка неоплаченных клиентов по OData: реализации/счета минус входящие оплаты по контрагенту. Для бухгалтерской точности сверяйте с отчетом по дебиторской задолженности 1С.")
        return {
            "sales_source": sales.get("source"),
            "incoming_payments_source": incoming.get("source"),
            "filters_applied_in_python": {
                "date_from": date_from,
                "date_to": date_to,
                "counterparty": counterparty,
            },
            "customer_count": len(rows),
            "rows": rows[:limit],
            "warnings": warnings,
        }

    def get_overdue_unpaid_customers(
        self,
        as_of_date: str | None = None,
        threshold_days: int = 3,
        date_from: str | None = None,
        counterparty: str | None = None,
        limit: int = 20,
        sales_entity_name: str | None = None,
        payment_entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Return customers with unpaid invoices older than threshold_days using FIFO settlement logic."""
        as_of = self._parse_date_like(as_of_date) or date.today()
        sales = self.get_sales_documents(
            date_from=date_from,
            date_to=as_of.isoformat(),
            counterparty=counterparty,
            limit=max(limit * 30, 300),
            entity_name=sales_entity_name,
        )
        incoming = self.get_payments(
            direction="incoming",
            date_from=date_from,
            date_to=as_of.isoformat(),
            counterparty=counterparty,
            limit=max(limit * 30, 300),
            entity_name=payment_entity_name,
        )
        settlement = self._build_customer_settlement(sales.get("data") or [], incoming.get("data") or [], as_of)
        overdue_rows: list[dict[str, Any]] = []
        for customer, info in settlement.items():
            overdue_amount = Decimal("0")
            oldest_days = 0
            overdue_docs = 0
            for invoice in info["open_invoices"]:
                invoice_date = invoice.get("invoice_date")
                if invoice_date is None:
                    continue
                age_days = (as_of - invoice_date).days
                if age_days > threshold_days and invoice["outstanding_amount"] > 0:
                    overdue_amount += invoice["outstanding_amount"]
                    overdue_docs += 1
                    oldest_days = max(oldest_days, age_days)
            if overdue_amount > 0:
                overdue_rows.append(
                    {
                        "counterparty": customer,
                        "overdue_amount": str(overdue_amount),
                        "overdue_invoice_count": overdue_docs,
                        "oldest_overdue_days": oldest_days,
                        "typical_payment_days": info["typical_payment_days"],
                        "closed_invoice_count_for_profile": info["closed_invoice_count"],
                        "open_amount_total": str(info["open_amount_total"]),
                    }
                )
        overdue_rows.sort(
            key=lambda x: (
                self._to_decimal(x["overdue_amount"], default=Decimal("0")),
                Decimal(str(x["oldest_overdue_days"])),
            ),
            reverse=True,
        )
        warnings = list(sales.get("warnings") or []) + list(incoming.get("warnings") or [])
        warnings.append("Просрочка рассчитана FIFO-методом по контрагенту: ранние входящие оплаты гасят самые старые реализации/счета.")
        return {
            "sales_source": sales.get("source"),
            "incoming_payments_source": incoming.get("source"),
            "filters_applied_in_python": {
                "as_of_date": as_of.isoformat(),
                "threshold_days": threshold_days,
                "date_from": date_from,
                "counterparty": counterparty,
            },
            "customer_count": len(overdue_rows),
            "rows": overdue_rows[:limit],
            "warnings": warnings,
        }

    def get_customer_payment_behavior_summary(
        self,
        as_of_date: str | None = None,
        date_from: str | None = None,
        counterparty: str | None = None,
        limit: int = 20,
        sales_entity_name: str | None = None,
        payment_entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Return average payment delay by customer based on fully settled invoices."""
        as_of = self._parse_date_like(as_of_date) or date.today()
        sales = self.get_sales_documents(
            date_from=date_from,
            date_to=as_of.isoformat(),
            counterparty=counterparty,
            limit=max(limit * 30, 300),
            entity_name=sales_entity_name,
        )
        incoming = self.get_payments(
            direction="incoming",
            date_from=date_from,
            date_to=as_of.isoformat(),
            counterparty=counterparty,
            limit=max(limit * 30, 300),
            entity_name=payment_entity_name,
        )
        settlement = self._build_customer_settlement(sales.get("data") or [], incoming.get("data") or [], as_of)
        rows: list[dict[str, Any]] = []
        for customer, info in settlement.items():
            rows.append(
                {
                    "counterparty": customer,
                    "typical_payment_days": info["typical_payment_days"],
                    "closed_invoice_count": info["closed_invoice_count"],
                    "open_amount_total": str(info["open_amount_total"]),
                    "billed_amount_total": str(info["billed_amount_total"]),
                    "paid_amount_total": str(info["paid_amount_total"]),
                }
            )
        rows.sort(
            key=lambda x: (
                -1 if x["typical_payment_days"] is None else 0,
                x["typical_payment_days"] if x["typical_payment_days"] is not None else 10**9,
            )
        )
        warnings = list(sales.get("warnings") or []) + list(incoming.get("warnings") or [])
        warnings.append("typical_payment_days считается только по полностью закрытым реализациям/счетам.")
        return {
            "sales_source": sales.get("source"),
            "incoming_payments_source": incoming.get("source"),
            "filters_applied_in_python": {
                "as_of_date": as_of.isoformat(),
                "date_from": date_from,
                "counterparty": counterparty,
            },
            "customer_count": len(rows),
            "rows": rows[:limit],
            "warnings": warnings,
        }

    def get_payments(
        self,
        direction: str,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty: str | None = None,
        limit: int = 50,
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Read incoming or outgoing payment-like rows from OData using metadata heuristics."""
        normalized_direction = self._normalize_payment_direction(direction)
        if entity_name:
            entity = self.describe_entity(entity_name)
            if entity is None:
                raise ODataError(f"Сущность не найдена: {entity_name}")
            score, reasons, entity_direction = self._score_payment_entity(entity)
            if entity_direction != normalized_direction:
                raise ODataError(
                    f"Сущность {entity_name} выглядит как payment direction={entity_direction}, а запрошено direction={normalized_direction}."
                )
            mapped = self._map_payment_fields([f.name for f in (entity.fields or [])])
            source = {
                "entity": entity.name,
                "direction": entity_direction,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
            }
        else:
            sources = self.discover_payment_sources(direction=normalized_direction, limit=1, check_data=True)
            if not sources:
                raise ODataError(
                    f"Не найден кандидат на источник платежей direction={normalized_direction}. Запустите discover_payment_sources для диагностики."
                )
            source = sources[0]

        mapped = source.get("mapped_fields") or {}
        select = self._build_payment_select(mapped)
        raw = self.query_entity(source["entity"], top=min(limit * 5, self.settings.max_top), select=select or None)
        rows = raw.get("data") or []
        normalized = [self._normalize_payment_row(r, mapped, source.get("direction")) for r in rows]

        effective_from = date or date_from
        effective_to = date or date_to
        warnings: list[str] = []
        if effective_from or effective_to:
            normalized = [
                r for r in normalized
                if self._date_in_range(r.get("date"), effective_from, effective_to)
            ]
        if counterparty:
            normalized = [
                r for r in normalized
                if self._text_match(r.get("counterparty"), counterparty) or self._text_match(r.get("raw"), counterparty)
            ]
        if not mapped.get("counterparty"):
            warnings.append("Не найдено явное поле контрагента. Проверьте mapped_fields и сущность вручную.")
        if not mapped.get("amount"):
            warnings.append("Не найдено явное поле суммы. Возможна неполная интерпретация платежей.")
        if not mapped.get("date"):
            warnings.append("Не найдено явное поле даты. Фильтрация по периоду могла сработать не для всех строк.")

        counterparty_totals: dict[str, Decimal] = {}
        total_amount = Decimal("0")
        amount_missing = 0
        for row in normalized[:limit]:
            amount = self._to_decimal(row.get("amount"), default=None)
            if amount is None:
                amount_missing += 1
                continue
            total_amount += amount
            name = str(row.get("counterparty") or "<unknown>")
            counterparty_totals[name] = counterparty_totals.get(name, Decimal("0")) + amount

        grouped = [
            {"counterparty": name, "amount": str(amount)}
            for name, amount in sorted(counterparty_totals.items(), key=lambda x: x[1], reverse=True)
        ]
        if amount_missing:
            warnings.append(f"Строк без распознанной суммы: {amount_missing}.")

        return {
            "source": source,
            "filters_applied_in_python": {
                "direction": normalized_direction,
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
                "counterparty": counterparty,
            },
            "count_returned": min(len(normalized), limit),
            "total_amount": str(total_amount),
            "grouped_by_counterparty": grouped[: min(limit, 20)],
            "data": normalized[:limit],
            "warnings": warnings,
            "note": "Платежи определены по metadata-эвристике OData. Для критичных выплат и поступлений сверяйте с официальным отчетом 1С.",
        }

    def get_payment_summary_by_counterparty(
        self,
        direction: str,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty: str | None = None,
        limit: int = 20,
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate payments by counterparty for management reporting."""
        payments = self.get_payments(
            direction=direction,
            date=date,
            date_from=date_from,
            date_to=date_to,
            counterparty=counterparty,
            limit=max(limit * 20, 200),
            entity_name=entity_name,
        )

        grouped: dict[str, dict[str, Any]] = {}
        total_amount = Decimal("0")
        for row in payments.get("data") or []:
            name = str(row.get("counterparty") or "<unknown>")
            amount = self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0")
            row_date = self._parse_date_like(row.get("date"))
            total_amount += amount
            bucket = grouped.setdefault(
                name,
                {
                    "counterparty": name,
                    "total_amount": Decimal("0"),
                    "payment_count": 0,
                    "first_payment_date": None,
                    "last_payment_date": None,
                },
            )
            bucket["total_amount"] += amount
            bucket["payment_count"] += 1
            if row_date:
                iso = row_date.isoformat()
                if bucket["first_payment_date"] is None or iso < bucket["first_payment_date"]:
                    bucket["first_payment_date"] = iso
                if bucket["last_payment_date"] is None or iso > bucket["last_payment_date"]:
                    bucket["last_payment_date"] = iso

        summary_rows = sorted(grouped.values(), key=lambda x: x["total_amount"], reverse=True)[:limit]
        for row in summary_rows:
            row["total_amount"] = str(row["total_amount"])

        return {
            "source": payments.get("source"),
            "filters_applied_in_python": payments.get("filters_applied_in_python"),
            "direction": self._normalize_payment_direction(direction),
            "total_amount": str(total_amount),
            "counterparty_count": len(grouped),
            "rows": summary_rows,
            "warnings": payments.get("warnings") or [],
            "note": "Это агрегированный управленческий срез по контрагентам на основе найденных платежных документов OData.",
        }

    def setup_wizard(self, check_live_entities: bool = False, live_limit: int = 30) -> dict[str, Any]:
        """Run first-install diagnostics for the OData bridge."""
        checks: list[dict[str, Any]] = []
        recommendations: list[str] = []

        url_ok = bool(self.settings.odata_url)
        checks.append({"name": "ONEC_ODATA_URL configured", "status": "ok" if url_ok else "error", "details": self.settings.odata_url or "not set"})
        checks.append({"name": "credentials configured", "status": "ok" if (self.settings.username and self.settings.password) else "warning", "details": "username/password set" if (self.settings.username and self.settings.password) else "username or password missing"})
        checks.append({"name": "ssl verification", "status": "ok" if self.settings.verify_ssl else "warning", "details": self.settings.verify_ssl})

        metadata_ok = False
        entities: list[EntityInfo] = []
        try:
            xml = self.get_metadata_xml(refresh=True)
            metadata_ok = True
            checks.append({"name": "$metadata readable", "status": "ok", "details": {"bytes": len(xml)}})
            entities = self.list_entities(refresh=False)
            checks.append({"name": "entities parsed", "status": "ok" if entities else "warning", "details": {"entity_count": len(entities)}})
        except Exception as exc:
            checks.append({"name": "$metadata readable", "status": "error", "details": str(exc)[:500]})
            recommendations.append("Проверьте URL публикации OData, логин/пароль, права пользователя и доступность веб-сервера 1С.")

        categories = self._entity_category_summary(entities) if entities else {}
        inventory_sources: list[dict[str, Any]] = []
        if metadata_ok:
            try:
                inventory_sources = self.discover_inventory_sources(limit=5, check_data=True)
                checks.append({"name": "inventory source candidates", "status": "ok" if inventory_sources else "warning", "details": {"count": len(inventory_sources), "top": inventory_sources[:2]}})
                if not inventory_sources:
                    recommendations.append("Не найдены кандидаты источников остатков. Проверьте, опубликованы ли регистры накопления и нужные объекты OData.")
            except Exception as exc:
                checks.append({"name": "inventory source candidates", "status": "warning", "details": str(exc)[:500]})

        live_entities: list[dict[str, Any]] = []
        if check_live_entities and metadata_ok:
            try:
                live_entities = self.explore_live_entities(limit=live_limit)
                live_count = sum(1 for x in live_entities if x.get("has_data") is True)
                checks.append({"name": "live entity scan", "status": "ok", "details": {"checked": len(live_entities), "with_data": live_count}})
            except Exception as exc:
                checks.append({"name": "live entity scan", "status": "warning", "details": str(exc)[:500]})

        if inventory_sources:
            recommendations.append("Сформируйте Материальную ведомость в 1С и сверяйте первый результат get_inventory_auto через validate_inventory_report_text.")
        recommendations.append("Для обычной работы используйте ask_1c: пользователь пишет текстом, JSON вручную не нужен.")

        status = "ready" if metadata_ok and entities else "needs_attention"
        if any(c["status"] == "error" for c in checks):
            status = "error"

        return {
            "status": status,
            "server": "ashybulakstroy-1c-bridge",
            "mode": "read-only",
            "checks": checks,
            "entity_summary": categories,
            "inventory_candidates": inventory_sources,
            "live_entities_sample": live_entities[:20],
            "next_steps": recommendations,
        }

    def generate_database_profile(self, check_inventory_data: bool = True, live_limit: int = 0) -> dict[str, Any]:
        """Build a compact profile of the published 1C OData model."""
        entities = self.list_entities(refresh=False)
        summary = self._entity_category_summary(entities)
        searches = {
            "inventory_keywords": self._rank_entities_by_terms(entities, ["остат", "stock", "inventory", "товар", "тмз", "склад", "quantity", "количество"], limit=15),
            "sales_keywords": self._rank_entities_by_terms(entities, ["реализац", "продаж", "sale", "sales", "выруч", "покупател"], limit=15),
            "purchase_keywords": self._rank_entities_by_terms(entities, ["поступлен", "закуп", "purchase", "поставщик", "приобрет"], limit=15),
            "payment_keywords": self._rank_entities_by_terms(entities, ["платеж", "оплат", "списание", "поступление", "bank", "cash", "касс", "счет"], limit=15),
            "counterparty_keywords": self._rank_entities_by_terms(entities, ["контрагент", "counterparty", "partner", "поставщик", "покупател"], limit=15),
            "nomenclature_keywords": self._rank_entities_by_terms(entities, ["номенклатур", "товар", "product", "item", "material", "материал"], limit=15),
        }
        inventory_candidates = self.discover_inventory_sources(limit=10, check_data=check_inventory_data)
        payment_candidates = self.discover_payment_sources(limit=10, check_data=check_inventory_data)
        sales_candidates = self.discover_sales_sources(limit=10, check_data=check_inventory_data)
        live_entities: list[dict[str, Any]] = []
        if live_limit and live_limit > 0:
            live_entities = self.explore_live_entities(limit=live_limit)

        risks: list[str] = []
        if not inventory_candidates:
            risks.append("Не найден надежный источник остатков по metadata. Возможно, нужные регистры не опубликованы в OData.")
        elif inventory_candidates[0].get("confidence") != "high":
            risks.append("Лучший кандидат источника остатков имеет не высокий confidence. Нужна сверка с отчетом 1С.")
        if summary.get("total", 0) == 0:
            risks.append("Не распознаны OData-сущности. Проверьте $metadata.")
        if live_entities and not any(x.get("has_data") is True for x in live_entities):
            risks.append("В проверенной выборке не найдены сущности с данными. Возможно, нет прав или выбран пустой сегмент metadata.")

        return {
            "server": "ashybulakstroy-1c-bridge",
            "mode": "read-only",
            "entity_summary": summary,
            "top_business_candidates": searches,
            "inventory_candidates": inventory_candidates,
            "payment_candidates": payment_candidates,
            "sales_candidates": sales_candidates,
            "live_entities_sample": live_entities[:30],
            "risks": risks,
            "recommended_next_actions": [
                "Запустите get_inventory_auto с малым limit=20.",
                "Сформируйте тот же отчет в 1С и вставьте таблицу в validate_inventory_report_text.",
                "После совпадения сохраните verified recipe для стабильного повторного использования.",
            ],
        }

    def _entity_category_summary(self, entities: list[EntityInfo]) -> dict[str, Any]:
        buckets = {"catalogs": 0, "documents": 0, "accumulation_registers": 0, "information_registers": 0, "accounting_registers": 0, "other": 0}
        samples: dict[str, list[str]] = {k: [] for k in buckets}
        for e in entities:
            n = self._norm(e.name + " " + (e.entity_type or ""))
            if "catalog" in n or "справочник" in n:
                key = "catalogs"
            elif "document" in n or "документ" in n:
                key = "documents"
            elif "accumulationregister" in n or "регистрнакопления" in n:
                key = "accumulation_registers"
            elif "informationregister" in n or "регистрсведений" in n:
                key = "information_registers"
            elif "accountingregister" in n or "регистрбухгалтерии" in n:
                key = "accounting_registers"
            else:
                key = "other"
            buckets[key] += 1
            if len(samples[key]) < 10:
                samples[key].append(e.name)
        return {"total": len(entities), "counts": buckets, "samples": samples}

    def _rank_entities_by_terms(self, entities: list[EntityInfo], terms: list[str], limit: int = 15) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        norm_terms = [self._norm(t) for t in terms]
        for e in entities:
            haystack = self._norm(" ".join([e.name, e.entity_type or "", *[f.name for f in (e.fields or [])]]))
            matched = [t for t in norm_terms if t and t in haystack]
            if matched:
                ranked.append({"entity": e.name, "entity_type": e.entity_type, "score": len(matched), "matched_terms": matched[:10], "field_count": len(e.fields or [])})
        return sorted(ranked, key=lambda x: x["score"], reverse=True)[:limit]

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not value or not _IDENTIFIER_RE.match(value):
            raise ODataError(f"Недопустимое значение {label}: {value!r}")

    @staticmethod
    def _norm(value: str | None) -> str:
        return (value or "").lower().replace("_", "").replace(".", "")

    def _score_inventory_entity(self, entity: EntityInfo) -> tuple[int, list[str]]:
        name = self._norm(entity.name)
        etype = self._norm(entity.entity_type)
        field_names = [self._norm(f.name) for f in (entity.fields or [])]
        haystack = " ".join([name, etype, *field_names])
        score = 0
        reasons: list[str] = []

        weighted_terms = {
            "accumulationregister": 18,
            "регистрнакопления": 18,
            "остат": 22,
            "stock": 18,
            "inventory": 18,
            "товар": 14,
            "тмз": 14,
            "номенклатур": 14,
            "материал": 10,
            "склад": 12,
            "warehouse": 12,
            "количество": 10,
            "quantity": 10,
            "сумма": 6,
            "amount": 6,
            "виртуальн": 4,
        }
        for term, weight in weighted_terms.items():
            if term in haystack:
                score += weight
                reasons.append(f"match:{term}")

        mapped = self._map_inventory_fields([f.name for f in (entity.fields or [])])
        for key, weight in {"item": 15, "warehouse": 12, "quantity": 15, "amount": 6, "period": 4}.items():
            if mapped.get(key):
                score += weight
                reasons.append(f"field:{key}={mapped[key]}")

        # Penalize obvious non-register catalogs/documents that only mention items casually.
        if "catalog" in name or "справочник" in name:
            score -= 12
            reasons.append("penalty:catalog")
        if "document" in name or "документ" in name:
            score -= 8
            reasons.append("penalty:document")
        return score, reasons

    def _map_inventory_fields(self, field_names: list[str]) -> dict[str, str | None]:
        patterns: dict[str, list[str]] = {
            "item": ["номенклатур", "товар", "item", "product", "материал"],
            "warehouse": ["склад", "warehouse", "местохран", "подразделение"],
            "quantity": ["количествоостаток", "количество", "quantity", "qty", "остаток"],
            "amount": ["суммаостаток", "сумма", "amount", "стоимость", "cost"],
            "period": ["period", "период", "date", "дата", "моментвремени"],
        }
        mapped: dict[str, str | None] = {k: None for k in patterns}
        normalized = [(name, self._norm(name)) for name in field_names]
        for key, terms in patterns.items():
            exactish = [x for x in normalized if any(x[1] == t for t in terms)]
            contains = [x for x in normalized if any(t in x[1] for t in terms)]
            choice = (exactish or contains or [(None, "")])[0][0]
            mapped[key] = choice
        return mapped

    def _score_payment_entity(self, entity: EntityInfo) -> tuple[int, list[str], str | None]:
        name = self._norm(entity.name)
        etype = self._norm(entity.entity_type)
        field_names = [self._norm(f.name) for f in (entity.fields or [])]
        haystack = " ".join([name, etype, *field_names])
        score = 0
        reasons: list[str] = []

        base_terms = {
            "document": 6,
            "документ": 6,
            "payment": 18,
            "платеж": 18,
            "оплат": 18,
            "cash": 10,
            "bank": 10,
            "касс": 10,
            "банк": 10,
            "счет": 8,
            "счета": 8,
            "counterparty": 8,
            "контрагент": 8,
            "amount": 8,
            "сумма": 8,
            "date": 4,
            "дата": 4,
            "period": 4,
            "период": 4,
        }
        for term, weight in base_terms.items():
            if term in haystack:
                score += weight
                reasons.append(f"match:{term}")

        outgoing_terms = [
            "списаниесбанковскогосчета",
            "списаниесрасчетногосчета",
            "расходныйкассовыйордер",
            "outgoing",
            "расход",
            "выдан",
            "supplierpayment",
        ]
        incoming_terms = [
            "поступлениенабанковскийсчет",
            "поступлениенарасчетныйсчет",
            "приходныйкассовыйордер",
            "incoming",
            "приход",
            "получен",
            "customerpayment",
        ]
        outgoing_score = sum(20 for term in outgoing_terms if term in haystack)
        incoming_score = sum(20 for term in incoming_terms if term in haystack)
        direction: str | None = None
        if outgoing_score > incoming_score and outgoing_score > 0:
            direction = "outgoing"
            score += outgoing_score
            reasons.append("direction:outgoing")
        elif incoming_score > outgoing_score and incoming_score > 0:
            direction = "incoming"
            score += incoming_score
            reasons.append("direction:incoming")

        mapped = self._map_payment_fields([f.name for f in (entity.fields or [])])
        for key, weight in {"counterparty": 14, "amount": 15, "date": 12, "number": 4}.items():
            if mapped.get(key):
                score += weight
                reasons.append(f"field:{key}={mapped[key]}")

        if "catalog" in name or "справочник" in name:
            score -= 14
            reasons.append("penalty:catalog")
        if not direction:
            score -= 8
            reasons.append("penalty:unknown_direction")
        return score, reasons, direction

    def _score_sales_entity(self, entity: EntityInfo) -> tuple[int, list[str]]:
        name = self._norm(entity.name)
        etype = self._norm(entity.entity_type)
        field_names = [self._norm(f.name) for f in (entity.fields or [])]
        haystack = " ".join([name, etype, *field_names])
        score = 0
        reasons: list[str] = []

        terms = {
            "document": 6,
            "документ": 6,
            "реализац": 20,
            "sale": 18,
            "sales": 18,
            "счетнаплату": 16,
            "счетнапокупателю": 16,
            "invoice": 16,
            "customer": 10,
            "buyer": 10,
            "покупател": 10,
            "контрагент": 10,
            "amount": 8,
            "сумма": 8,
            "date": 4,
            "дата": 4,
            "number": 4,
            "номер": 4,
        }
        for term, weight in terms.items():
            if term in haystack:
                score += weight
                reasons.append(f"match:{term}")

        mapped = self._map_sales_fields([f.name for f in (entity.fields or [])])
        for key, weight in {"counterparty": 14, "amount": 15, "date": 12, "number": 4}.items():
            if mapped.get(key):
                score += weight
                reasons.append(f"field:{key}={mapped[key]}")

        if "catalog" in name or "справочник" in name:
            score -= 14
            reasons.append("penalty:catalog")
        return score, reasons

    def _map_payment_fields(self, field_names: list[str]) -> dict[str, str | None]:
        patterns: dict[str, list[str]] = {
            "counterparty": ["контрагент", "partner", "counterparty", "client", "customer", "supplier", "получатель", "плательщик"],
            "amount": ["суммадокумента", "сумма", "amount", "paymentamount", "total"],
            "date": ["дата", "date", "period", "период", "documentdate"],
            "number": ["номер", "number", "documentnumber"],
            "organization": ["организация", "organization", "company"],
            "bank_account": ["банковскийсчет", "bankaccount", "счеторганизации", "касса", "cashbox"],
        }
        mapped: dict[str, str | None] = {k: None for k in patterns}
        normalized = [(name, self._norm(name)) for name in field_names]
        for key, terms in patterns.items():
            exactish = [x for x in normalized if any(x[1] == self._norm(t) for t in terms)]
            contains = [x for x in normalized if any(self._norm(t) in x[1] for t in terms)]
            choice = (exactish or contains or [(None, "")])[0][0]
            mapped[key] = choice
        return mapped

    def _map_sales_fields(self, field_names: list[str]) -> dict[str, str | None]:
        patterns: dict[str, list[str]] = {
            "counterparty": ["контрагент", "partner", "counterparty", "client", "customer", "buyer", "покупатель"],
            "amount": ["суммадокумента", "сумма", "amount", "total"],
            "date": ["дата", "date", "period", "период", "documentdate"],
            "number": ["номер", "number", "documentnumber"],
            "organization": ["организация", "organization", "company"],
        }
        mapped: dict[str, str | None] = {k: None for k in patterns}
        normalized = [(name, self._norm(name)) for name in field_names]
        for key, terms in patterns.items():
            exactish = [x for x in normalized if any(x[1] == self._norm(t) for t in terms)]
            contains = [x for x in normalized if any(self._norm(t) in x[1] for t in terms)]
            choice = (exactish or contains or [(None, "")])[0][0]
            mapped[key] = choice
        return mapped

    @staticmethod
    def _confidence_from_score(score: int) -> str:
        if score >= 85:
            return "high"
        if score >= 55:
            return "medium"
        return "low"

    @staticmethod
    def _build_inventory_select(mapped: dict[str, str | None]) -> list[str]:
        out: list[str] = []
        for key in ("item", "warehouse", "quantity", "amount", "period"):
            value = mapped.get(key)
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _build_payment_select(mapped: dict[str, str | None]) -> list[str]:
        out: list[str] = []
        for key in ("counterparty", "amount", "date", "number", "organization", "bank_account"):
            value = mapped.get(key)
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _build_sales_select(mapped: dict[str, str | None]) -> list[str]:
        out: list[str] = []
        for key in ("counterparty", "amount", "date", "number", "organization"):
            value = mapped.get(key)
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _normalize_inventory_row(row: dict[str, Any], mapped: dict[str, str | None]) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        return {
            "item": pick("item"),
            "warehouse": pick("warehouse"),
            "quantity": pick("quantity"),
            "amount": pick("amount"),
            "period": pick("period"),
            "raw": row,
        }

    @staticmethod
    def _normalize_payment_row(row: dict[str, Any], mapped: dict[str, str | None], direction: str | None) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        return {
            "direction": direction,
            "counterparty": pick("counterparty"),
            "amount": pick("amount"),
            "date": pick("date"),
            "number": pick("number"),
            "organization": pick("organization"),
            "bank_account": pick("bank_account"),
            "raw": row,
        }

    @staticmethod
    def _normalize_sales_row(row: dict[str, Any], mapped: dict[str, str | None]) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        return {
            "counterparty": pick("counterparty"),
            "amount": pick("amount"),
            "date": pick("date"),
            "number": pick("number"),
            "organization": pick("organization"),
            "raw": row,
        }

    def _build_customer_settlement(
        self,
        sales_rows: list[dict[str, Any]],
        payment_rows: list[dict[str, Any]],
        as_of: date,
    ) -> dict[str, dict[str, Any]]:
        customers = sorted({str((r.get("counterparty") or "<unknown>")) for r in [*sales_rows, *payment_rows]})
        settlement: dict[str, dict[str, Any]] = {}
        for customer in customers:
            customer_sales = [
                {
                    "invoice_date": self._parse_date_like(row.get("date")),
                    "invoice_number": row.get("number"),
                    "amount": self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0"),
                }
                for row in sales_rows
                if str(row.get("counterparty") or "<unknown>") == customer
            ]
            customer_payments = [
                {
                    "payment_date": self._parse_date_like(row.get("date")),
                    "amount": self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0"),
                }
                for row in payment_rows
                if str(row.get("counterparty") or "<unknown>") == customer
            ]
            customer_sales.sort(key=lambda x: (x["invoice_date"] or date.min, str(x.get("invoice_number") or "")))
            customer_payments.sort(key=lambda x: (x["payment_date"] or date.min))

            open_invoices: list[dict[str, Any]] = []
            closed_days: list[int] = []
            billed_total = Decimal("0")
            for invoice in customer_sales:
                billed_total += invoice["amount"]
                open_invoices.append(
                    {
                        "invoice_date": invoice["invoice_date"],
                        "invoice_number": invoice["invoice_number"],
                        "amount": invoice["amount"],
                        "outstanding_amount": invoice["amount"],
                        "closed_date": None,
                    }
                )

            paid_total = Decimal("0")
            for payment in customer_payments:
                remaining_payment = payment["amount"]
                paid_total += payment["amount"]
                for invoice in open_invoices:
                    if remaining_payment <= 0:
                        break
                    outstanding = invoice["outstanding_amount"]
                    if outstanding <= 0:
                        continue
                    applied = min(outstanding, remaining_payment)
                    invoice["outstanding_amount"] -= applied
                    remaining_payment -= applied
                    if invoice["outstanding_amount"] <= 0 and invoice["closed_date"] is None:
                        invoice["closed_date"] = payment["payment_date"]
                        if invoice["invoice_date"] and payment["payment_date"]:
                            closed_days.append((payment["payment_date"] - invoice["invoice_date"]).days)

            open_amount_total = sum((invoice["outstanding_amount"] for invoice in open_invoices), Decimal("0"))
            typical_payment_days = None
            if closed_days:
                typical_payment_days = round(sum(closed_days) / len(closed_days), 2)

            settlement[customer] = {
                "open_invoices": open_invoices,
                "closed_invoice_count": len(closed_days),
                "typical_payment_days": typical_payment_days,
                "open_amount_total": open_amount_total,
                "billed_amount_total": billed_total,
                "paid_amount_total": paid_total,
                "as_of": as_of.isoformat(),
            }
        return settlement

    @staticmethod
    def _to_decimal(value: Any, default: Decimal | None = Decimal("0")) -> Decimal | None:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return default
        text = text.replace("\u00a0", " ").replace(" ", "")
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return default

    @staticmethod
    def _severity_rank(value: Any) -> int:
        return {"critical": 0, "high": 1, "medium": 2}.get(str(value), 9)

    @staticmethod
    def _text_match(value: Any, needle: str) -> bool:
        if value is None:
            return False
        return needle.lower() in str(value).lower()

    @staticmethod
    def _normalize_payment_direction(value: str | None) -> str:
        direction = (value or "").strip().lower()
        if direction in {"outgoing", "payment_out", "paid", "expense", "расход", "исходящий", "out"}:
            return "outgoing"
        if direction in {"incoming", "payment_in", "received", "income", "приход", "входящий", "in"}:
            return "incoming"
        raise ODataError(f"Недопустимое направление платежа: {value!r}. Используйте incoming или outgoing.")

    @staticmethod
    def _parse_date_like(value: Any) -> date | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        candidates = [
            text,
            text[:10],
            text.replace(" ", "T"),
        ]
        for candidate in candidates:
            try:
                if len(candidate) == 10:
                    return date.fromisoformat(candidate)
                return datetime.fromisoformat(candidate).date()
            except ValueError:
                continue
        return None

    def _date_in_range(self, value: Any, date_from: str | None, date_to: str | None) -> bool:
        row_date = self._parse_date_like(value)
        if row_date is None:
            return False
        from_date = self._parse_date_like(date_from) if date_from else None
        to_date = self._parse_date_like(date_to) if date_to else None
        if from_date and row_date < from_date:
            return False
        if to_date and row_date > to_date:
            return False
        return True
