from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any, Callable

import httpx

from .config import Settings
from .security.audit import AuditLogger
from .security.context import get_request_context

log = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-zА-Яа-я0-9_\.]+$")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


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
    def __init__(self, settings: Settings, audit_logger: AuditLogger | None = None):
        self.settings = settings
        self.audit_logger = audit_logger
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
        self._reference_cache: dict[tuple[str, str, tuple[str, ...]], dict[str, Any] | None] = {}

    def _require_url(self) -> None:
        if not self.settings.odata_url:
            raise ODataError("ONEC_ODATA_URL не задан. Заполните .env или переменные окружения.")

    def _url(self, path: str) -> str:
        self._require_url()
        return f"{self.settings.odata_url}/{path.lstrip('/')}"

    def get_metadata_xml(self, refresh: bool = False) -> str:
        if self._metadata_xml is not None and not refresh:
            return self._metadata_xml
        response = self._get("$metadata", headers={"Accept": "application/xml"})
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
        entity_types: dict[str, list[FieldInfo]] = {}
        for et in root.iter():
            if self._xml_local_name(et.tag) != "EntityType":
                continue
            et_name = et.attrib.get("Name")
            if not et_name:
                continue
            fields: list[FieldInfo] = []
            for prop in et:
                if self._xml_local_name(prop.tag) != "Property":
                    continue
                fields.append(
                    FieldInfo(
                        name=prop.attrib.get("Name", ""),
                        type=prop.attrib.get("Type"),
                        nullable=(prop.attrib.get("Nullable", "true").lower() != "false"),
                    )
                )
            entity_types[et_name] = fields

        entities: list[EntityInfo] = []
        for container in root.iter():
            if self._xml_local_name(container.tag) != "EntityContainer":
                continue
            for entity_set in container:
                if self._xml_local_name(entity_set.tag) != "EntitySet":
                    continue
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

        response = self._get(entity_name, params=params)
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

    def _get(self, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        started = perf_counter()
        error: str | None = None
        response: httpx.Response | None = None
        try:
            response = self.client.get(self._url(path), params=params, headers=headers)
            return response
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            self._audit_adapter_call(
                path=path,
                params=params,
                status_code=response.status_code if response is not None else None,
                duration_ms=int((perf_counter() - started) * 1000),
                error=error,
            )

    def _audit_adapter_call(
        self,
        *,
        path: str,
        params: dict[str, Any] | None,
        status_code: int | None,
        duration_ms: int,
        error: str | None,
    ) -> None:
        if self.audit_logger is None:
            return
        ctx = get_request_context()
        self.audit_logger.append(
            {
                "timestamp": datetime.now().astimezone().isoformat(),
                "stage": "1c_adapter_call",
                "actor": ctx.actor if ctx else "mcp_client",
                "project_id": ctx.project_id if ctx else None,
                "agent_id": ctx.agent_id if ctx else None,
                "policy_id": ctx.policy_id if ctx else None,
                "session_id": ctx.session_id if ctx else None,
                "trace_id": ctx.trace_id if ctx else None,
                "tool": ctx.tool_name if ctx else None,
                "risk": ctx.risk_level if ctx else None,
                "capabilities": list(ctx.capabilities) if ctx else [],
                "decision": ctx.decision if ctx else "allow",
                "policy_version": ctx.policy_version if ctx else None,
                "provider": ctx.provider if ctx else None,
                "adapter": "odata",
                "method": "GET",
                "path": path,
                "params": params or {},
                "status_code": status_code,
                "duration_ms": duration_ms,
                "error": error,
            }
        )

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
            candidates.append(row)

        ranked = sorted(candidates, key=lambda r: r["score"], reverse=True)
        if check_data:
            for row in ranked[: min(max(limit * 3, 10), 20)]:
                try:
                    sample = self.query_entity(row["entity"], top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 10
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
        return sorted(
            ranked,
            key=lambda r: (
                1 if r.get("has_data") is True else 0,
                r["score"],
            ),
            reverse=True,
        )[:limit]

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
                "account_type": self._classify_payment_account_type(entity.name),
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
                "field_count": len(field_names),
                "sample_fields": field_names[:40],
            }
            candidates.append(row)

        ranked = sorted(
            candidates,
            key=lambda r: (
                1 if self._is_preferred_payment_source_entity(r.get("entity")) else 0,
                1 if r.get("direction") in {"incoming", "outgoing"} else 0,
                r["score"],
                1 if r.get("has_data") is True else 0,
                1 if r.get("account_type") == "bank" else 0,
            ),
            reverse=True,
        )
        if check_data:
            for row in ranked[: min(max(limit * 3, 10), 20)]:
                try:
                    sample = self.query_entity(row["entity"], top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 8
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
        return sorted(
            ranked,
            key=lambda r: (
                1 if self._is_preferred_payment_source_entity(r.get("entity")) else 0,
                1 if r.get("direction") in {"incoming", "outgoing"} else 0,
                r["score"],
                1 if r.get("has_data") is True else 0,
                1 if r.get("account_type") == "bank" else 0,
            ),
            reverse=True,
        )[:limit]

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
            candidates.append(row)

        ranked = sorted(candidates, key=lambda r: r["score"], reverse=True)
        if check_data:
            for row in ranked[: min(max(limit * 3, 10), 20)]:
                try:
                    sample = self.query_entity(row["entity"], top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 8
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
        return sorted(
            ranked,
            key=lambda r: (
                1 if r.get("has_data") is True else 0,
                r["score"],
            ),
            reverse=True,
        )[:limit]

    def discover_purchase_sources(
        self,
        limit: int = 10,
        check_data: bool = True,
    ) -> list[dict[str, Any]]:
        """Find likely purchase/supplier invoice entities using metadata heuristics."""
        candidates: list[dict[str, Any]] = []
        for entity in self.list_entities():
            score, reasons = self._score_purchase_entity(entity)
            if score <= 0:
                continue
            fields = entity.fields or []
            field_names = [f.name for f in fields]
            mapped = self._map_purchase_fields(field_names)
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
            candidates.append(row)

        ranked = sorted(candidates, key=lambda r: r["score"], reverse=True)
        if check_data:
            for row in ranked[: min(max(limit * 3, 10), 20)]:
                try:
                    sample = self.query_entity(row["entity"], top=1)
                    row["has_data"] = bool(sample.get("data"))
                    row["sample"] = (sample.get("data") or [])[:1]
                    if row["has_data"]:
                        row["score"] += 8
                        row["confidence"] = self._confidence_from_score(row["score"])
                        row["reasons"].append("entity_has_data")
                except Exception as exc:
                    row["has_data"] = None
                    row["error"] = str(exc)[:300]
        return sorted(
            ranked,
            key=lambda r: (
                1 if r.get("has_data") is True else 0,
                r["score"],
            ),
            reverse=True,
        )[:limit]

    def get_sales_documents(
        self,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty: str | None = None,
        limit: int = 100,
        entity_name: str | None = None,
        include_sections: bool = False,
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
        select = None if include_sections else self._build_sales_select(mapped)
        effective_from = date or date_from
        effective_to = date or date_to
        filter_expr = self._build_common_text_date_filter(
            mapped,
            date_from=effective_from,
            date_to=effective_to,
            text_field_key="counterparty",
            text_value=counterparty,
        )
        query_top = min(max(limit, 50), self.settings.max_top)
        try:
            raw = self.query_entity(
                source["entity"],
                top=query_top,
                select=select or None,
                filter_expr=filter_expr or None,
            )
            filter_fallback_used = False
        except ODataError as exc:
            if filter_expr and self._is_unsupported_where_filter_error(exc):
                raw = self.query_entity(
                    source["entity"],
                    top=min(max(limit * 3, 100), self.settings.max_top),
                    select=select or None,
                    filter_expr=None,
                )
                filter_fallback_used = True
            else:
                raise
        rows = raw.get("data") or []
        normalized = [self._normalize_sales_row(r, mapped) for r in rows]

        warnings: list[str] = []
        if filter_fallback_used:
            warnings.append("OData provider rejected pushdown filter for this source. Applied bounded Python-side filtering instead.")
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

    def get_procurement_recommendations(
        self,
        days: int = 30,
        as_of_date: str | None = None,
        warehouse: str | None = None,
        item: str | None = None,
        limit: int = 20,
        coverage_days: int | None = None,
    ) -> dict[str, Any]:
        """Return read-only procurement suggestions based on recent sales and current stock."""
        lookback_days = min(max(int(days), 1), 180)
        target_days = min(max(int(coverage_days or lookback_days), 1), 180)
        effective_limit = min(max(int(limit), 1), 30)
        explicit_as_of = self._parse_date_like(as_of_date) if as_of_date else None
        if as_of_date and explicit_as_of is None:
            raise ODataError(f"Некорректная дата as_of_date: {as_of_date!r}. Используйте YYYY-MM-DD.")

        sales_source_probe = self.discover_sales_sources(limit=1, check_data=True)
        if not sales_source_probe:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "days": lookback_days,
                    "as_of_date": as_of_date,
                    "warehouse": warehouse,
                    "item": item,
                    "limit": effective_limit,
                    "coverage_days": target_days,
                },
                "missing_sources": ["sales_documents"],
                "warnings": ["Не найден безопасный источник продаж/реализаций для расчета закупа по спросу."],
                "source_explanation": {
                    "inventory_source": None,
                    "sales_source": None,
                    "basis": "source_missing",
                },
                "note": "Закуп не рассчитан, потому что не найден published read-only источник продаж.",
            }

        probe_limit = min(max(effective_limit * 20, 200), self.settings.max_top)
        sales_probe = self.get_sales_documents(limit=probe_limit, entity_name=sales_source_probe[0]["entity"], include_sections=True)
        sales_dates = [
            self._parse_date_like(row.get("date"))
            for row in sales_probe.get("data") or []
            if self._parse_date_like(row.get("date")) is not None
        ]
        inferred_as_of = explicit_as_of or (max(sales_dates) if sales_dates else date.today())
        window_start = inferred_as_of - timedelta(days=lookback_days - 1)

        inventory = self.get_inventory_auto(warehouse=warehouse, item=item, limit=min(max(effective_limit * 20, 200), self.settings.max_top))
        sales = self.get_sales_documents(
            date_from=window_start.isoformat(),
            date_to=inferred_as_of.isoformat(),
            limit=probe_limit,
            entity_name=sales_source_probe[0]["entity"],
            include_sections=True,
        )

        sales_source = sales.get("source") or {}
        inventory_source = inventory.get("source") or {}

        sold_by_item: dict[str, dict[str, Any]] = {}
        sales_doc_count_by_item: dict[str, set[str]] = {}
        for row in sales.get("data") or []:
            doc_number = str(row.get("number") or "")
            raw = row.get("raw") or {}
            line_items = self._extract_sales_line_items(raw)
            for line in line_items:
                item_name = str(line.get("name") or "").strip()
                if not item_name:
                    continue
                if item and not self._text_match(item_name, item):
                    continue
                qty = self._to_decimal(line.get("quantity"), default=None)
                amount = self._to_decimal(line.get("amount"), default=Decimal("0")) or Decimal("0")
                if qty is None or qty <= 0:
                    continue
                bucket = sold_by_item.setdefault(
                    item_name,
                    {
                        "sold_quantity": Decimal("0"),
                        "sales_amount": Decimal("0"),
                    },
                )
                bucket["sold_quantity"] += qty
                bucket["sales_amount"] += amount
                sales_doc_count_by_item.setdefault(item_name, set()).add(doc_number)

        current_stock_by_item: dict[str, Decimal] = {}
        warehouse_by_item: dict[str, str | None] = {}
        for row in inventory.get("data") or []:
            item_name = str(row.get("item") or "").strip()
            if not item_name:
                continue
            qty = self._to_decimal(row.get("quantity"), default=Decimal("0")) or Decimal("0")
            current_stock_by_item[item_name] = current_stock_by_item.get(item_name, Decimal("0")) + qty
            warehouse_by_item[item_name] = row.get("warehouse")

        rows: list[dict[str, Any]] = []
        day_divisor = Decimal(str(lookback_days))
        coverage_multiplier = Decimal(str(target_days))
        for item_name, sales_info in sold_by_item.items():
            sold_qty = sales_info["sold_quantity"]
            current_stock = current_stock_by_item.get(item_name, Decimal("0"))
            daily_rate = sold_qty / day_divisor if day_divisor else Decimal("0")
            target_stock = daily_rate * coverage_multiplier
            recommended_qty = target_stock - current_stock
            if recommended_qty <= 0:
                continue
            stock_days_left = None
            if daily_rate > 0:
                stock_days_left = float((current_stock / daily_rate).quantize(Decimal("0.01")))
            rows.append(
                {
                    "item": item_name,
                    "warehouse": warehouse_by_item.get(item_name),
                    "sold_quantity_last_days": self._decimal_to_text(sold_qty),
                    "sales_amount_last_days": self._decimal_to_text(sales_info["sales_amount"]),
                    "daily_sales_rate": self._decimal_to_text(daily_rate.quantize(Decimal("0.01"))),
                    "current_stock": self._decimal_to_text(current_stock),
                    "target_stock_for_period": self._decimal_to_text(target_stock.quantize(Decimal("0.01"))),
                    "recommended_purchase_qty": self._decimal_to_text(recommended_qty.quantize(Decimal("0.01"))),
                    "stock_days_left": stock_days_left,
                    "sales_document_count": len(sales_doc_count_by_item.get(item_name, set())),
                    "inventory_source": inventory_source.get("entity"),
                    "sales_source": sales_source.get("entity"),
                    "reason": f"sales_{lookback_days}_days_gt_current_stock_for_next_{target_days}_days",
                }
            )

        rows.sort(
            key=lambda row: (
                self._to_decimal(row.get("recommended_purchase_qty"), default=Decimal("0")) or Decimal("0"),
                self._to_decimal(row.get("sold_quantity_last_days"), default=Decimal("0")) or Decimal("0"),
            ),
            reverse=True,
        )

        warnings = list(inventory.get("warnings") or [])
        warnings.extend(sales.get("warnings") or [])
        warnings.append(
            "Это read-only управленческая рекомендация закупа: продажи за период и текущий остаток из published OData. Это не официальный MRP-расчет 1С."
        )

        return {
            "count_returned": min(len(rows), effective_limit),
            "data": rows[:effective_limit],
            "filters_applied_in_python": {
                "days": lookback_days,
                "as_of_date": inferred_as_of.isoformat(),
                "warehouse": warehouse,
                "item": item,
                "limit": effective_limit,
                "coverage_days": target_days,
            },
            "source_explanation": {
                "inventory_source": inventory_source.get("entity"),
                "sales_source": sales_source.get("entity"),
                "basis": "recent_sales_and_current_stock",
            },
            "warnings": warnings,
            "note": "Read-only procurement estimate only. Основан на продажах за период и текущем остатке, без записи в 1С.",
        }

    def get_purchase_documents(
        self,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty: str | None = None,
        limit: int = 100,
        entity_name: str | None = None,
        include_sections: bool = False,
    ) -> dict[str, Any]:
        """Read purchase/supplier-invoice-like rows from OData using metadata heuristics."""
        if entity_name:
            entity = self.describe_entity(entity_name)
            if entity is None:
                raise ODataError(f"Сущность не найдена: {entity_name}")
            score, reasons = self._score_purchase_entity(entity)
            mapped = self._map_purchase_fields([f.name for f in (entity.fields or [])])
            source = {
                "entity": entity.name,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
            }
        else:
            sources = self.discover_purchase_sources(limit=1, check_data=True)
            if not sources:
                raise ODataError("Не найден кандидат на источник поступлений/счетов поставщика. Запустите discover_purchase_sources для диагностики.")
            source = sources[0]

        mapped = source.get("mapped_fields") or {}
        select = None if include_sections else self._build_purchase_select(mapped)
        effective_from = date or date_from
        effective_to = date or date_to
        filter_expr = self._build_common_text_date_filter(
            mapped,
            date_from=effective_from,
            date_to=effective_to,
            text_field_key="counterparty",
            text_value=counterparty,
        )
        query_top = min(max(limit, 50), self.settings.max_top)
        try:
            raw = self.query_entity(
                source["entity"],
                top=query_top,
                select=select or None,
                filter_expr=filter_expr or None,
            )
            filter_fallback_used = False
        except ODataError as exc:
            if filter_expr and self._is_unsupported_where_filter_error(exc):
                raw = self.query_entity(
                    source["entity"],
                    top=min(max(limit * 3, 100), self.settings.max_top),
                    select=select or None,
                    filter_expr=None,
                )
                filter_fallback_used = True
            else:
                raise
        rows = raw.get("data") or []
        normalized = [self._normalize_sales_row(r, mapped) for r in rows]

        warnings: list[str] = []
        if filter_fallback_used:
            warnings.append("OData provider rejected pushdown filter for this source. Applied bounded Python-side filtering instead.")
        if effective_from or effective_to:
            normalized = [r for r in normalized if self._date_in_range(r.get("date"), effective_from, effective_to)]
        if counterparty:
            normalized = [r for r in normalized if self._text_match(r.get("counterparty"), counterparty) or self._text_match(r.get("raw"), counterparty)]
        if not mapped.get("counterparty"):
            warnings.append("Не найдено явное поле поставщика/контрагента в источнике поступлений.")
        if not mapped.get("amount"):
            warnings.append("Не найдено явное поле суммы в источнике поступлений.")
        if not mapped.get("date"):
            warnings.append("Не найдено явное поле даты в источнике поступлений.")

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
            "note": "Поступления/счета поставщика определены по metadata-эвристике OData. Для точного учета кредиторки сверяйте с официальными отчетами 1С.",
        }

    def search_document_by_number(
        self,
        document_number: str,
        document_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search document-like OData entities by document number without exposing raw OData to the caller."""
        needle = str(document_number or "").strip()
        if not needle:
            raise ODataError("document_number не должен быть пустым.")

        effective_limit = min(max(int(limit), 1), 20)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        candidate_limit = self._document_search_candidate_limit(document_type=document_type, result_limit=effective_limit)
        candidates = self._discover_document_search_candidates(document_type=document_type, limit=candidate_limit)
        if not candidates:
            return self._empty_document_search_result(
                needle=needle,
                document_type=document_type,
                date_from=validated_from,
                date_to=validated_to,
                limit=effective_limit,
                warnings=[
                    "Не найдено document-like OData сущностей для поиска по номеру. "
                    "Проверьте публикацию документов в OData или уточните document_type."
                ],
            )

        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        checked_candidates = 0
        for candidate in candidates:
            mapped = candidate.get("mapped_fields") or {}
            if not mapped.get("number"):
                warnings.append(f"Пропущена сущность {candidate['entity']}: не найдено поле номера документа.")
                continue
            checked_candidates += 1
            select = self._build_document_select(mapped)
            filter_expr = self._build_document_search_filter(
                mapped,
                document_number=needle,
                date_from=validated_from,
                date_to=validated_to,
            )
            orderby = f"{mapped['date']} desc" if mapped.get("date") else None
            query_top = min(effective_limit, self.settings.max_top)
            filter_fallback_used = False
            try:
                raw = self.query_entity(
                    candidate["entity"],
                    top=query_top,
                    select=select or None,
                    filter_expr=filter_expr or None,
                    orderby=orderby,
                )
            except ODataError as exc:
                if filter_expr and self._is_unsupported_where_filter_error(exc):
                    try:
                        raw = self.query_entity(
                            candidate["entity"],
                            top=min(max(effective_limit * 2, 20), 60, self.settings.max_top),
                            select=select or None,
                            filter_expr=None,
                            orderby=orderby,
                        )
                        filter_fallback_used = True
                    except ODataError as fallback_exc:
                        warnings.append(
                            f"Источник {candidate['entity']} пропущен: provider rejected $filter and bounded fallback read "
                            "is not accessible for this entity in current 1C publication."
                        )
                        if self._is_access_denied_error(fallback_exc):
                            continue
                        raise
                else:
                    raise
            if filter_fallback_used:
                warnings.append(
                    f"OData provider rejected pushdown filter for {candidate['entity']}. "
                    "Applied bounded Python-side filtering instead."
                )
            for row in raw.get("data") or []:
                normalized = self._normalize_document_search_row(row, candidate["entity"], mapped)
                if not self._text_match(normalized.get("number"), needle):
                    continue
                if (validated_from or validated_to) and not self._date_in_range(normalized.get("date"), validated_from, validated_to):
                    continue
                rows.append(normalized)
            if len(rows) >= effective_limit and (document_type or checked_candidates >= 3):
                warnings.append("Поиск остановлен после достижения лимита в наиболее релевантных document-like источниках.")
                break

        rows.sort(
            key=lambda item: (
                self._parse_date_like(item.get("date")) or date.min,
                str(item.get("number") or ""),
                str(item.get("document_type") or ""),
            ),
            reverse=True,
        )

        return {
            "document_number": needle,
            "document_type_filter": document_type,
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "limit": effective_limit,
                "candidate_limit": candidate_limit,
            },
            "matched_entities": sorted({str(row.get("document_type") or "") for row in rows if row.get("document_type")}),
            "count_returned": min(len(rows), effective_limit),
            "data": rows[:effective_limit],
            "warnings": warnings,
            "note": "Поиск выполнен через безопасный read-only wrapper поверх document-like OData сущностей без raw OData для агента.",
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

    def get_customer_settlements_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        min_debt: Any = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return a safe receivables-style summary from sales and incoming payments."""
        effective_limit = min(max(int(limit), 1), 50)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        as_of = self._parse_date_like(validated_to) or date.today()
        min_debt_amount = self._parse_decimal_input(min_debt, field_name="min_debt", default=Decimal("0"))
        fetch_limit = min(max(effective_limit * 10, 200), self.settings.max_top)

        sales: dict[str, Any] | None = None
        incoming: dict[str, Any] | None = None
        missing_sources: list[str] = []
        warnings: list[str] = []

        try:
            sales = self.get_sales_documents(
                date_from=validated_from,
                date_to=validated_to,
                counterparty=counterparty_name,
                limit=fetch_limit,
            )
        except ODataError:
            missing_sources.append("sales_documents")
            warnings.append(
                "Не найден безопасный источник реализаций/счетов для расчета взаиморасчетов. "
                "Источник не опубликован в OData, недоступен по правам или не распознан по metadata."
            )

        try:
            incoming = self.get_payments(
                direction="incoming",
                date_from=validated_from,
                date_to=validated_to,
                counterparty=counterparty_name,
                limit=fetch_limit,
            )
        except ODataError:
            missing_sources.append("incoming_payments")
            warnings.append(
                "Не найден безопасный источник входящих оплат для расчета взаиморасчетов. "
                "Источник не опубликован в OData, недоступен по правам или не распознан по metadata."
            )

        if sales is None or incoming is None:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "min_debt": str(min_debt_amount),
                    "limit": effective_limit,
                },
                "missing_sources": missing_sources,
                "source_explanation": {
                    "sales_documents_used": None,
                    "incoming_payments_used": None,
                    "missing_sources": missing_sources,
                    "basis": "summary_not_built",
                },
                "warnings": warnings,
                "note": "Сводка не построена, потому что в OData не найден один из обязательных read-only источников: реализации/счета и входящие оплаты. Это не официальный бухгалтерский акт сверки и не баланс взаиморасчетов.",
            }

        settlement = self._build_customer_settlement(sales.get("data") or [], incoming.get("data") or [], as_of)
        last_payment_dates = self._last_payment_dates_by_customer(incoming.get("data") or [])
        sales_source = sales.get("source") or {}
        incoming_source = incoming.get("source") or {}

        rows: list[dict[str, Any]] = []
        for customer, info in settlement.items():
            debt_amount = info["open_amount_total"]
            if debt_amount <= 0 or debt_amount < min_debt_amount:
                continue
            overdue_days = self._calculate_overdue_days(info.get("open_invoices") or [], as_of)
            rows.append(
                {
                    "counterparty": customer,
                    "bin_or_iin": info.get("counterparty_bin_or_iin"),
                    "debt_amount": str(debt_amount),
                    "currency": None,
                    "last_payment_date": last_payment_dates.get(customer),
                    "overdue_days": overdue_days,
                    "source_document_count": len(info.get("open_invoices") or []),
                    "source_entity": sales_source.get("entity"),
                }
            )

        rows.sort(
            key=lambda row: (
                self._to_decimal(row.get("debt_amount"), default=Decimal("0")) or Decimal("0"),
                Decimal(str(row.get("overdue_days") or 0)),
            ),
            reverse=True,
        )

        warnings.extend(sales.get("warnings") or [])
        warnings.extend(incoming.get("warnings") or [])
        warnings.append(
            "Это управленческая read-only оценка взаиморасчетов по OData: реализации/счета минус входящие оплаты по контрагенту. "
            "Это не официальный бухгалтерский акт сверки и не баланс взаиморасчетов. Для бухгалтерской точности сверяйте с официальным отчетом 1С по взаиморасчетам."
        )

        return {
            "count_returned": min(len(rows), effective_limit),
            "data": rows[:effective_limit],
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "min_debt": str(min_debt_amount),
                "limit": effective_limit,
            },
            "sales_source": sales_source,
            "incoming_payments_source": incoming_source,
            "missing_sources": missing_sources,
            "source_explanation": {
                "sales_documents_used": sales_source.get("entity"),
                "incoming_payments_used": incoming_source.get("entity"),
                "missing_sources": missing_sources,
                "basis": "sales_documents_minus_incoming_payments_by_counterparty",
            },
            "warnings": warnings,
            "note": "Read-only management estimate only. Не является официальным бухгалтерским актом сверки или балансом взаиморасчетов.",
        }

    def get_supplier_settlements_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        min_debt: Any = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return a safe payables-style summary from purchases and outgoing payments."""
        effective_limit = min(max(int(limit), 1), 50)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        as_of = self._parse_date_like(validated_to) or date.today()
        min_debt_amount = self._parse_decimal_input(min_debt, field_name="min_debt", default=Decimal("0"))
        fetch_limit = min(max(effective_limit * 10, 200), self.settings.max_top)

        purchases: dict[str, Any] | None = None
        outgoing: dict[str, Any] | None = None
        missing_sources: list[str] = []
        warnings: list[str] = []

        try:
            purchases = self.get_purchase_documents(
                date_from=validated_from,
                date_to=validated_to,
                counterparty=counterparty_name,
                limit=fetch_limit,
            )
        except ODataError:
            missing_sources.append("purchase_documents")
            warnings.append(
                "Не найден безопасный источник поступлений/счетов поставщика для расчета кредиторки. "
                "Источник не опубликован в OData, недоступен по правам или не распознан по metadata."
            )

        try:
            outgoing = self.get_payments(
                direction="outgoing",
                date_from=validated_from,
                date_to=validated_to,
                counterparty=counterparty_name,
                limit=fetch_limit,
            )
        except ODataError:
            missing_sources.append("outgoing_payments")
            warnings.append(
                "Не найден безопасный источник исходящих оплат для расчета кредиторки. "
                "Источник не опубликован в OData, недоступен по правам или не распознан по metadata."
            )

        if purchases is None or outgoing is None:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "min_debt": str(min_debt_amount),
                    "limit": effective_limit,
                },
                "missing_sources": missing_sources,
                "source_explanation": {
                    "purchase_documents_used": None,
                    "outgoing_payments_used": None,
                    "missing_sources": missing_sources,
                    "basis": "summary_not_built",
                },
                "warnings": warnings,
                "note": "Сводка не построена, потому что в OData не найден один из обязательных read-only источников: поступления/счета поставщика и исходящие оплаты. Это не официальный бухгалтерский акт сверки и не баланс взаиморасчетов.",
            }

        settlement = self._build_customer_settlement(purchases.get("data") or [], outgoing.get("data") or [], as_of)
        last_payment_dates = self._last_payment_dates_by_customer(outgoing.get("data") or [])
        purchase_source = purchases.get("source") or {}
        outgoing_source = outgoing.get("source") or {}

        rows: list[dict[str, Any]] = []
        for supplier, info in settlement.items():
            debt_amount = info["open_amount_total"]
            if debt_amount <= 0 or debt_amount < min_debt_amount:
                continue
            overdue_days = self._calculate_overdue_days(info.get("open_invoices") or [], as_of)
            rows.append(
                {
                    "counterparty": supplier,
                    "bin_or_iin": info.get("counterparty_bin_or_iin"),
                    "debt_amount": str(debt_amount),
                    "currency": None,
                    "last_payment_date": last_payment_dates.get(supplier),
                    "overdue_days": overdue_days,
                    "source_document_count": len(info.get("open_invoices") or []),
                    "source_entity": purchase_source.get("entity"),
                }
            )

        rows.sort(
            key=lambda row: (
                self._to_decimal(row.get("debt_amount"), default=Decimal("0")) or Decimal("0"),
                Decimal(str(row.get("overdue_days") or 0)),
            ),
            reverse=True,
        )

        warnings.extend(purchases.get("warnings") or [])
        warnings.extend(outgoing.get("warnings") or [])
        warnings.append(
            "Это управленческая read-only оценка кредиторки по OData: поступления/счета поставщика минус исходящие оплаты по контрагенту. "
            "Это не официальный бухгалтерский акт сверки и не баланс взаиморасчетов. Для бухгалтерской точности сверяйте с официальным отчетом 1С по кредиторской задолженности."
        )

        return {
            "count_returned": min(len(rows), effective_limit),
            "data": rows[:effective_limit],
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "min_debt": str(min_debt_amount),
                "limit": effective_limit,
            },
            "purchase_source": purchase_source,
            "outgoing_payments_source": outgoing_source,
            "missing_sources": missing_sources,
            "source_explanation": {
                "purchase_documents_used": purchase_source.get("entity"),
                "outgoing_payments_used": outgoing_source.get("entity"),
                "missing_sources": missing_sources,
                "basis": "purchase_documents_minus_outgoing_payments_by_counterparty",
            },
            "warnings": warnings,
            "note": "Read-only management estimate only. Не является официальным бухгалтерским актом сверки или балансом взаиморасчетов.",
        }

    def get_supplier_debt_document_breakdown(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        min_debt: Any = None,
        limit: int = 10,
        documents_per_supplier: int = 5,
    ) -> dict[str, Any]:
        """Return document-level safe breakdown for supplier payables."""
        effective_limit = min(max(int(limit), 1), 20)
        docs_limit = min(max(int(documents_per_supplier), 1), 10)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        as_of = self._parse_date_like(validated_to) or date.today()
        min_debt_amount = self._parse_decimal_input(min_debt, field_name="min_debt", default=Decimal("0"))
        fetch_limit = min(max(effective_limit * 10, 200), self.settings.max_top)

        summary = self.get_supplier_settlements_summary(
            date_from=validated_from,
            date_to=validated_to,
            counterparty_name=counterparty_name,
            min_debt=min_debt_amount,
            limit=effective_limit,
        )
        purchase_source = summary.get("purchase_source") or {}
        outgoing_source = summary.get("outgoing_payments_source") or {}
        if not purchase_source or not outgoing_source:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "min_debt": str(min_debt_amount),
                    "limit": effective_limit,
                    "documents_per_supplier": docs_limit,
                },
                "missing_sources": summary.get("missing_sources") or [],
                "warnings": summary.get("warnings") or [],
                "note": "Document breakdown не построен, потому что нет безопасных read-only источников закупок или исходящих оплат.",
            }

        purchases = self.get_purchase_documents(
            date_from=validated_from,
            date_to=validated_to,
            counterparty=counterparty_name,
            limit=fetch_limit,
            entity_name=purchase_source.get("entity"),
            include_sections=False,
        )
        outgoing = self.get_payments(
            direction="outgoing",
            date_from=validated_from,
            date_to=validated_to,
            counterparty=counterparty_name,
            limit=fetch_limit,
            entity_name=outgoing_source.get("entity"),
        )
        settlement = self._build_customer_settlement(purchases.get("data") or [], outgoing.get("data") or [], as_of)
        detail_rows: list[dict[str, Any]] = []
        warnings = list(summary.get("warnings") or [])

        for supplier_row in summary.get("data") or []:
            supplier_name = str(supplier_row.get("counterparty") or "")
            supplier_info = settlement.get(supplier_name)
            if not supplier_info:
                continue
            open_docs = [
                invoice
                for invoice in supplier_info.get("open_invoices") or []
                if (invoice.get("outstanding_amount") or Decimal("0")) > 0
            ]
            if not open_docs:
                continue
            detailed = self.get_purchase_documents(
                date_from=validated_from,
                date_to=validated_to,
                counterparty=supplier_name,
                limit=min(max(docs_limit * 4, 20), 100),
                entity_name=purchase_source.get("entity"),
                include_sections=True,
            )
            warnings.extend(detailed.get("warnings") or [])
            open_doc_map = {
                self._purchase_invoice_key(invoice): invoice
                for invoice in open_docs
            }
            document_rows: list[dict[str, Any]] = []
            for row in detailed.get("data") or []:
                key = self._purchase_invoice_key(
                    {
                        "invoice_number": row.get("number"),
                        "invoice_date": self._parse_date_like(row.get("date")),
                        "amount": self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0"),
                    }
                )
                invoice = open_doc_map.get(key)
                if invoice is None:
                    continue
                amount_total = self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0")
                outstanding_amount = invoice.get("outstanding_amount") or Decimal("0")
                paid_amount = amount_total - outstanding_amount
                section_summary = self._summarize_purchase_document_sections(row.get("raw") or {})
                document_rows.append(
                    {
                        "document_date": row.get("date"),
                        "document_number": row.get("number"),
                        "document_total_amount": str(amount_total),
                        "outstanding_amount": str(outstanding_amount),
                        "paid_amount_estimate": str(paid_amount if paid_amount > 0 else Decimal("0")),
                        "currency": row.get("currency"),
                        "organization": row.get("organization"),
                        "overdue_days": self._calculate_overdue_days([invoice], as_of),
                        "line_items_sample": section_summary["line_items_sample"],
                        "section_counts": section_summary["section_counts"],
                        "line_summary_text": section_summary["line_summary_text"],
                    }
                )
            document_rows.sort(
                key=lambda item: (
                    self._to_decimal(item.get("outstanding_amount"), default=Decimal("0")) or Decimal("0"),
                    self._parse_date_like(item.get("document_date")) or date.min,
                ),
                reverse=True,
            )
            detail_rows.append(
                {
                    "counterparty": supplier_name,
                    "bin_or_iin": supplier_row.get("bin_or_iin"),
                    "debt_amount": supplier_row.get("debt_amount"),
                    "last_payment_date": supplier_row.get("last_payment_date"),
                    "overdue_days": supplier_row.get("overdue_days"),
                    "source_entity": supplier_row.get("source_entity"),
                    "documents": document_rows[:docs_limit],
                }
            )

        return {
            "count_returned": min(len(detail_rows), effective_limit),
            "data": detail_rows[:effective_limit],
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "min_debt": str(min_debt_amount),
                "limit": effective_limit,
                "documents_per_supplier": docs_limit,
            },
            "purchase_source": purchase_source,
            "outgoing_payments_source": outgoing_source,
            "warnings": warnings,
            "note": "Read-only document-level management estimate only. Не является официальным бухгалтерским актом сверки или балансом взаиморасчетов.",
        }

    def get_supplier_reconciliation_documents(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        limit: int = 20,
        lines_per_document: int = 6,
    ) -> dict[str, Any]:
        """Return safe read-only supplier reconciliation documents from published 1C acts."""
        effective_limit = min(max(int(limit), 1), 20)
        sample_lines_limit = min(max(int(lines_per_document), 1), 10)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        entity_name = "Document_АктСверкиВзаиморасчетов"
        entity = self.describe_entity(entity_name)
        if entity is None:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "limit": effective_limit,
                    "lines_per_document": sample_lines_limit,
                },
                "missing_sources": ["supplier_reconciliation_documents"],
                "warnings": [
                    "В OData не найден опубликованный Document_АктСверкиВзаиморасчетов. Нельзя проверить долг по более официальному published источнику."
                ],
                "source_explanation": {
                    "source_entity": None,
                    "basis": "source_missing",
                    "missing_sources": ["supplier_reconciliation_documents"],
                },
                "note": "Published acts of reconciliation were not found in OData. Используйте управленческую read-only оценку или попросите 1С-сторону опубликовать источник сверки.",
            }

        fetch_limit = min(max(effective_limit * 10, 100), self.settings.max_top)
        select = [
            "Ref_Key",
            "Number",
            "Date",
            "Контрагент_Key",
            "Организация_Key",
            "ДатаНачала",
            "ДатаОкончания",
            "ОстатокНаНачало",
            "Расхождение",
            "СверкаСогласована",
            "ПоДаннымОрганизации",
            "ПоДаннымКонтрагента",
        ]
        filter_parts: list[str] = []
        if validated_from:
            literal = self._to_odata_datetime_literal(validated_from, end_of_day=False)
            if literal:
                filter_parts.append(f"ДатаОкончания ge {literal}")
        if validated_to:
            literal = self._to_odata_datetime_literal(validated_to, end_of_day=True)
            if literal:
                filter_parts.append(f"ДатаОкончания le {literal}")
        filter_expr = " and ".join(filter_parts) if filter_parts else None

        try:
            payload = self.query_entity(
                entity_name=entity_name,
                top=fetch_limit,
                select=select,
                filter_expr=filter_expr,
                orderby="Date desc",
            )
        except ODataError:
            payload = self.query_entity(
                entity_name=entity_name,
                top=fetch_limit,
                select=select,
                orderby="Date desc",
            )

        rows: list[dict[str, Any]] = []
        for raw in payload.get("data") or []:
            period_end = raw.get("ДатаОкончания") or raw.get("Date")
            if not self._date_in_range(period_end, validated_from, validated_to):
                continue
            counterparty_info = self._resolve_counterparty_info(raw.get("Контрагент_Key"))
            counterparty_display = counterparty_info.get("display") or raw.get("Контрагент_Key")
            if counterparty_name and not self._text_match(counterparty_display, counterparty_name):
                continue
            summary = self._summarize_supplier_reconciliation_document(
                raw,
                counterparty_display=str(counterparty_display or "<unknown>"),
                bin_or_iin=counterparty_info.get("bin_or_iin"),
                sample_lines_limit=sample_lines_limit,
            )
            if summary is None:
                continue
            rows.append(summary)

        rows.sort(
            key=lambda row: (
                self._parse_date_like(row.get("reconciliation_date")) or date.min,
                self._to_decimal(row.get("balance_estimate_by_organization_view"), default=Decimal("0")) or Decimal("0"),
            ),
            reverse=True,
        )

        return {
            "count_returned": min(len(rows), effective_limit),
            "data": rows[:effective_limit],
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "limit": effective_limit,
                "lines_per_document": sample_lines_limit,
            },
            "source_explanation": {
                "source_entity": entity_name,
                "basis": "published_reconciliation_documents_from_1c",
                "missing_sources": [],
            },
            "warnings": [
                "Это read-only published source из 1С: уже существующие акты сверки взаиморасчетов. Источник ближе к официальной сверке, чем эвристика по поступлениям и оплатам, но все равно зависит от того, какие акты реально заведены и опубликованы в OData."
            ],
            "note": "Read-only published reconciliation document view. Это чтение уже существующих актов сверки в 1С, а не формирование нового отчета.",
        }

    def get_cash_bank_movements(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        movement_type: str | None = None,
        account_type: str | None = None,
        counterparty_name: str | None = None,
        min_amount: Any = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return a safe read-only list of incoming/outgoing cash and bank movements."""
        effective_limit = min(max(int(limit), 1), 100)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        normalized_movement_type = self._validate_choice(
            movement_type,
            allowed={"incoming", "outgoing", "all"},
            default="all",
            field_name="movement_type",
        )
        normalized_account_type = self._validate_choice(
            account_type,
            allowed={"bank", "cash", "all"},
            default="all",
            field_name="account_type",
        )
        min_amount_value = self._parse_decimal_input(min_amount, field_name="min_amount", default=Decimal("0"))
        fetch_limit = min(max(effective_limit, 50), self.settings.max_top)
        directions = ["incoming", "outgoing"] if normalized_movement_type == "all" else [normalized_movement_type]

        rows: list[dict[str, Any]] = []
        missing_sources: list[str] = []
        warnings: list[str] = []
        incoming_sources_used: list[str] = []
        outgoing_sources_used: list[str] = []
        skipped_without_amount = 0

        for direction in directions:
            candidates = self.discover_payment_sources(direction=direction, limit=20, check_data=True)
            filtered_candidates = [
                source for source in candidates
                if self._is_preferred_payment_source_entity(source.get("entity"))
                and (normalized_account_type == "all" or self._classify_payment_account_type(source.get("entity")) == normalized_account_type)
            ]
            if not filtered_candidates:
                missing_sources.append(f"{direction}:{normalized_account_type}")
                continue

            for source in filtered_candidates:
                try:
                    movements = self.get_payments(
                        direction=direction,
                        date_from=validated_from,
                        date_to=validated_to,
                        counterparty=counterparty_name,
                        limit=fetch_limit,
                        entity_name=source["entity"],
                    )
                except ODataError:
                    warnings.append(
                        f"Источник {source.get('entity')} пропущен: данные недоступны или не распознаны безопасным OData-слоем."
                    )
                    continue

                account_kind = self._classify_payment_account_type(source.get("entity"))
                if direction == "incoming":
                    incoming_sources_used.append(str(source.get("entity")))
                else:
                    outgoing_sources_used.append(str(source.get("entity")))

                for row in movements.get("data") or []:
                    amount_value = self._to_decimal(row.get("amount"), default=None)
                    if amount_value is None:
                        skipped_without_amount += 1
                        continue
                    if amount_value < min_amount_value:
                        continue
                    rows.append(
                        {
                            "date": row.get("date"),
                            "movement_type": direction,
                            "account_type": account_kind,
                            "counterparty": row.get("counterparty"),
                            "amount": str(amount_value),
                            "currency": row.get("currency"),
                            "document_type": source.get("entity"),
                            "document_number": row.get("number"),
                            "purpose": row.get("purpose"),
                            "source_entity": source.get("entity"),
                        }
                    )

        rows.sort(
            key=lambda row: (
                self._parse_date_like(row.get("date")) or date.min,
                self._to_decimal(row.get("amount"), default=Decimal("0")) or Decimal("0"),
            ),
            reverse=True,
        )
        if skipped_without_amount:
            warnings.append(f"Пропущено движений без распознанной суммы: {skipped_without_amount}.")
        if missing_sources:
            warnings.append("Часть источников движений не найдена в OData. Проверьте публикацию документов банка/кассы.")

        return {
            "count_returned": min(len(rows), effective_limit),
            "data": rows[:effective_limit],
            "no_data_in_sources": not bool(rows),
            "published_sources_with_rows_found": bool(rows),
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "movement_type": normalized_movement_type,
                "account_type": normalized_account_type,
                "counterparty_name": counterparty_name,
                "min_amount": str(min_amount_value),
                "limit": effective_limit,
            },
            "missing_sources": missing_sources,
            "source_explanation": {
                "incoming_sources_checked": sorted(set(incoming_sources_used)),
                "outgoing_sources_checked": sorted(set(outgoing_sources_used)),
                "missing_sources": missing_sources,
                "basis": "payment_documents_classified_as_bank_or_cash",
            },
            "warnings": warnings,
            "note": "Read-only movement view only. Не является официальной банковской выпиской или кассовой книгой 1С.",
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
        effective_from = date or date_from
        effective_to = date or date_to
        source_candidates_checked: list[str] = []
        warnings: list[str] = []

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
            source_candidates = [{
                "entity": entity.name,
                "direction": entity_direction,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
            }]
        else:
            discovered_candidates = self.discover_payment_sources(direction=normalized_direction, limit=10, check_data=True)
            preferred_candidates = [
                candidate
                for candidate in discovered_candidates
                if self._is_preferred_payment_source_entity(candidate.get("entity"))
            ]
            source_candidates = preferred_candidates or discovered_candidates
            if not source_candidates:
                raise ODataError(
                    f"Не найден кандидат на источник платежей direction={normalized_direction}. Запустите discover_payment_sources для диагностики."
                )
        primary_source = source_candidates[0]
        source = source_candidates[0]
        normalized: list[dict[str, Any]] = []
        query_top = min(max(limit, 50), self.settings.max_top)
        chosen_filter_fallback_used = False

        for idx, candidate in enumerate(source_candidates):
            source_candidates_checked.append(str(candidate.get("entity")))
            mapped = candidate.get("mapped_fields") or {}
            select = self._build_payment_select(mapped)
            filter_expr = self._build_common_text_date_filter(
                mapped,
                date_from=effective_from,
                date_to=effective_to,
                text_field_key="counterparty",
                text_value=counterparty,
            )
            try:
                raw = self.query_entity(
                    candidate["entity"],
                    top=query_top,
                    select=select or None,
                    filter_expr=filter_expr or None,
                )
                filter_fallback_used = False
            except ODataError as exc:
                if filter_expr and self._is_unsupported_where_filter_error(exc):
                    raw = self.query_entity(
                        candidate["entity"],
                        top=min(max(limit * 3, 100), self.settings.max_top),
                        select=select or None,
                        filter_expr=None,
                    )
                    filter_fallback_used = True
                elif entity_name:
                    raise
                else:
                    warnings.append(f"Источник {candidate['entity']} пропущен: безопасное чтение не удалось.")
                    continue

            rows = raw.get("data") or []
            candidate_normalized = [self._normalize_payment_row(r, mapped, candidate.get("direction")) for r in rows]
            if effective_from or effective_to:
                candidate_normalized = [
                    r for r in candidate_normalized
                    if self._date_in_range(r.get("date"), effective_from, effective_to)
                ]
            if counterparty:
                candidate_normalized = [
                    r for r in candidate_normalized
                    if self._text_match(r.get("counterparty"), counterparty) or self._text_match(r.get("raw"), counterparty)
                ]

            source = candidate
            normalized = candidate_normalized
            chosen_filter_fallback_used = filter_fallback_used
            if entity_name or candidate_normalized:
                break
            if idx < len(source_candidates) - 1:
                warnings.append(f"Источник {candidate['entity']} не вернул строк по текущим фильтрам. Пробуем следующий safe candidate.")

        mapped = source.get("mapped_fields") or {}
        if chosen_filter_fallback_used:
            warnings.append("OData provider rejected pushdown filter for this source. Applied bounded Python-side filtering instead.")
        if not mapped.get("counterparty"):
            warnings.append("Не найдено явное поле контрагента. Проверьте mapped_fields и сущность вручную.")
        if not mapped.get("amount"):
            warnings.append("Не найдено явное поле суммы. Возможна неполная интерпретация платежей.")
        if not mapped.get("date"):
            warnings.append("Не найдено явное поле даты. Фильтрация по периоду могла сработать не для всех строк.")
        if not normalized:
            warnings.append("В текущей OData-публикации не найдено строк по проверенным payment-like safe sources для заданных фильтров.")
            if source_candidates_checked:
                warnings.append("Проверены только read-only business-level payment documents. Публикация не дала ни одной строки по этим источникам.")

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
            "source": source if normalized else primary_source,
            "last_checked_source": source,
            "source_candidates_checked": source_candidates_checked,
            "no_data_in_checked_sources": not bool(normalized),
            "source_candidates_mode": "preferred_top_level_documents" if not entity_name and source_candidates else "explicit_entity",
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
            "source_candidates_checked": payments.get("source_candidates_checked") or [],
            "no_data_in_sources": bool(payments.get("no_data_in_checked_sources")) and not bool(summary_rows),
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
        checks.append(
            {
                "name": "ONEC_ODATA_URL configured",
                "status": "ok" if url_ok else "error",
                "details": "configured" if url_ok else "not set",
            }
        )
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
        warnings: list[str] = []
        inventory_candidates = self._safe_profile_discovery(
            "inventory_candidates",
            lambda: self.discover_inventory_sources(limit=10, check_data=check_inventory_data),
            warnings,
        )
        payment_candidates = self._safe_profile_discovery(
            "payment_candidates",
            lambda: self.discover_payment_sources(limit=10, check_data=check_inventory_data),
            warnings,
        )
        sales_candidates = self._safe_profile_discovery(
            "sales_candidates",
            lambda: self.discover_sales_sources(limit=10, check_data=check_inventory_data),
            warnings,
        )
        live_entities: list[dict[str, Any]] = []
        if live_limit and live_limit > 0:
            try:
                live_entities = self.explore_live_entities(limit=live_limit)
            except Exception as exc:
                warnings.append(f"live_entities_sample: {type(exc).__name__}: {str(exc)[:200]}")

        risks: list[str] = []
        if not inventory_candidates:
            risks.append("Не найден надежный источник остатков по metadata. Возможно, нужные регистры не опубликованы в OData.")
        elif inventory_candidates[0].get("confidence") != "high":
            risks.append("Лучший кандидат источника остатков имеет не высокий confidence. Нужна сверка с отчетом 1С.")
        if summary.get("total", 0) == 0:
            risks.append("Не распознаны OData-сущности. Проверьте $metadata.")
        if live_entities and not any(x.get("has_data") is True for x in live_entities):
            risks.append("В проверенной выборке не найдены сущности с данными. Возможно, нет прав или выбран пустой сегмент metadata.")
        if warnings:
            risks.append("Часть profile discovery была деградирована в read-only partial mode. Проверьте warnings.")

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
            "warnings": warnings,
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

        preferred_inventory_terms = {
            "товарыорганизаций": 18,
            "товарынавиртуальныхскладах": 18,
            "товарывиртуальногоскладаврезерве": 16,
            "товарынаскладах": 20,
            "остатк": 18,
            "запасы": 10,
        }
        for term, weight in preferred_inventory_terms.items():
            if term in haystack:
                score += weight
                reasons.append(f"inventory_priority:{term}")

        movement_like_terms = {
            "реализация": 22,
            "реализациятмз": 26,
            "выпуск": 18,
            "корректировк": 14,
            "исходныетовары": 18,
            "электронныйдокументвс": 18,
            "эсф": 18,
            "инвентаризац": 10,
            "списание": 12,
        }
        for term, penalty in movement_like_terms.items():
            if term in haystack:
                score -= penalty
                reasons.append(f"penalty:{term}")

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
        if "_recordtype" not in name and "accumulationregister" in haystack:
            score -= 6
            reasons.append("penalty:register_container")
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
            "платежноепоручениеисходящее",
            "платежныйордерсписаниеденежныхсредств",
            "outgoing",
            "расход",
            "выдан",
            "supplierpayment",
        ]
        incoming_terms = [
            "поступлениенабанковскийсчет",
            "поступлениенарасчетныйсчет",
            "приходныйкассовыйордер",
            "платежноепоручениевходящее",
            "платежныйордерпоступлениеденежныхсредств",
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

        if any(term in haystack for term in ["списаниесбанковскогосчета", "списаниесрасчетногосчета", "поступлениенабанковскийсчет", "поступлениенарасчетныйсчет", "платежноепоручениеисходящее", "платежноепоручениевходящее", "платежныйордерпоступлениеденежныхсредств", "платежныйордерсписаниеденежныхсредств"]):
            score += 40
            reasons.append("account:bank_priority")
        elif any(term in haystack for term in ["расходныйкассовыйордер", "приходныйкассовыйордер"]):
            score += 18
            reasons.append("account:cash_priority")

        mapped = self._map_payment_fields([f.name for f in (entity.fields or [])])
        for key, weight in {"counterparty": 14, "amount": 15, "date": 12, "number": 4}.items():
            if mapped.get(key):
                score += weight
                reasons.append(f"field:{key}={mapped[key]}")

        if "catalog" in name or "справочник" in name:
            score -= 14
            reasons.append("penalty:catalog")
        if any(term in haystack for term in ["присоединенныефайлы", "удалитьэлектронныеподписи", "удалитьсертификатышифрования"]):
            score -= 50
            reasons.append("penalty:attachments")
        if any(term in haystack for term in ["счетфактура", "реализациятоваровуслуг", "передачаос", "передачанма", "авансовыйотчет", "возвраттоваровотпокупателя"]):
            score -= 36
            reasons.append("penalty:not_payment_document")
        if "_расшифровкаплатежа" in name or "_выдачавподотчет" in name or "_перечисление" in name:
            score -= 30
            reasons.append("penalty:tabular_or_specialized_section")
        if str(entity.name).count("_") > 1:
            score -= 14
            reasons.append("penalty:nested_document_section")
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

        preferred_sales_terms = {
            "реализациятоваровуслуг": 30,
            "реализацияуслугпопереработке": 20,
            "счетнаоплатупокупателю": 24,
            "оплатаотпокупателяплатежнойкартой": 8,
        }
        for term, weight in preferred_sales_terms.items():
            if term in haystack:
                score += weight
                reasons.append(f"sales_priority:{term}")

        non_sales_terms = {
            "счетфактуравыданный": 24,
            "счетфактураполученный": 30,
            "платежноепоручение": 30,
            "платежныйордер": 30,
            "актсверкивзаиморасчетов": 18,
            "чекккм": 10,
            "гтдимпорт": 12,
        }
        for term, penalty in non_sales_terms.items():
            if term in haystack:
                score -= penalty
                reasons.append(f"penalty:{term}")

        mapped = self._map_sales_fields([f.name for f in (entity.fields or [])])
        for key, weight in {"counterparty": 14, "amount": 15, "date": 12, "number": 4}.items():
            if mapped.get(key):
                score += weight
                reasons.append(f"field:{key}={mapped[key]}")

        if "catalog" in name or "справочник" in name:
            score -= 14
            reasons.append("penalty:catalog")
        return score, reasons

    def _score_purchase_entity(self, entity: EntityInfo) -> tuple[int, list[str]]:
        name = self._norm(entity.name)
        etype = self._norm(entity.entity_type)
        field_names = [self._norm(f.name) for f in (entity.fields or [])]
        haystack = " ".join([name, etype, *field_names])
        score = 0
        reasons: list[str] = []

        terms = {
            "document": 6,
            "документ": 6,
            "поступлен": 20,
            "purchase": 18,
            "supplier": 10,
            "поставщик": 10,
            "приобрет": 12,
            "счетнаоплатупоставщика": 16,
            "invoice": 10,
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

        preferred_purchase_terms = {
            "поступлениетоваровуслуг": 30,
            "поступлениедопрасходов": 16,
            "счетнаоплатупоставщика": 24,
            "поступлениенма": 14,
            "поступлениеизпереработки": 14,
        }
        for term, weight in preferred_purchase_terms.items():
            if term in haystack:
                score += weight
                reasons.append(f"purchase_priority:{term}")

        non_purchase_terms = {
            "реализациятоваровуслуг": 30,
            "реализацияуслугпопереработке": 24,
            "счетнаоплатупокупателю": 24,
            "платежноепоручение": 30,
            "платежныйордер": 30,
            "счетфактуравыданный": 30,
            "чекккм": 12,
            "гтдимпорт": 12,
        }
        for term, penalty in non_purchase_terms.items():
            if term in haystack:
                score -= penalty
                reasons.append(f"penalty:{term}")

        mapped = self._map_purchase_fields([f.name for f in (entity.fields or [])])
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
            "counterparty": ["контрагентkey", "контрагент", "partner", "counterparty", "client", "customer", "supplier", "получательkey", "получатель", "плательщикkey", "плательщик", "договорконтрагентакey"],
            "amount": ["суммадокумента", "суммаплатежа", "сумма", "amount", "paymentamount", "total"],
            "date": ["date", "дата", "period", "период", "documentdate"],
            "number": ["number", "номер", "documentnumber"],
            "organization": ["организацияkey", "организация", "organization", "company"],
            "bank_account": ["счеторганизацииkey", "банковскийсчетkey", "счетбанкkey", "кассаkey", "банковскийсчет", "bankaccount", "счеторганизации", "касса", "cashbox"],
            "currency": ["валютадокументаkey", "валютаkey", "валюта", "currency"],
            "purpose": ["назначениеплатежа", "комментарий", "comment", "purpose", "description"],
        }
        return self._map_fields_by_patterns(field_names, patterns)

    def _map_sales_fields(self, field_names: list[str]) -> dict[str, str | None]:
        patterns: dict[str, list[str]] = {
            "counterparty": ["контрагентkey", "контрагент", "customer", "buyer", "покупатель", "грузополучательkey", "грузополучатель", "договорконтрагентакey"],
            "amount": ["суммадокумента", "сумма", "amount", "total"],
            "date": ["date", "дата", "period", "период", "documentdate"],
            "number": ["number", "номер", "documentnumber"],
            "organization": ["организацияkey", "организация", "organization", "company"],
        }
        return self._map_fields_by_patterns(field_names, patterns)

    def _map_purchase_fields(self, field_names: list[str]) -> dict[str, str | None]:
        patterns: dict[str, list[str]] = {
            "counterparty": ["контрагентkey", "контрагент", "supplier", "vendor", "поставщик", "получательkey", "договорконтрагентакey"],
            "amount": ["суммадокумента", "сумма", "amount", "total"],
            "date": ["date", "дата", "period", "период", "documentdate"],
            "number": ["number", "номер", "documentnumber"],
            "organization": ["организацияkey", "организация", "organization", "company"],
            "currency": ["валютадокументаkey", "валютаkey", "валюта", "currency"],
        }
        return self._map_fields_by_patterns(field_names, patterns)

    def _map_document_fields(self, field_names: list[str]) -> dict[str, str | None]:
        patterns: dict[str, list[str]] = {
            "counterparty": ["контрагентkey", "контрагент", "customer", "buyer", "supplier", "покупатель", "поставщик", "грузополучательkey", "грузополучатель", "договорконтрагентакey"],
            "amount": ["суммадокумента", "сумма", "amount", "total"],
            "date": ["date", "дата", "period", "период", "documentdate"],
            "number": ["number", "номер", "documentnumber"],
            "status": ["статус", "status", "state"],
            "posted": ["posted", "проведен", "проведён"],
            "reference": ["refkey", "ref_key", "ссылка", "ref", "id", "key"],
            "deletion_mark": ["deletionmark", "пометкаудаления", "markedfordeletion", "isdeleted"],
        }
        return self._map_fields_by_patterns(field_names, patterns)

    def _map_fields_by_patterns(self, field_names: list[str], patterns: dict[str, list[str]]) -> dict[str, str | None]:
        mapped: dict[str, str | None] = {k: None for k in patterns}
        normalized = [(name, self._norm(name)) for name in field_names]
        for key, terms in patterns.items():
            normalized_terms = [self._norm(t) for t in terms]
            exactish = [x for x in normalized if any(x[1] == term for term in normalized_terms)]
            starts = [x for x in normalized if any(x[1].startswith(term) for term in normalized_terms)]
            contains = [x for x in normalized if any(term in x[1] for term in normalized_terms)]
            choice = (exactish or starts or contains or [(None, "")])[0][0]
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
        for key in ("counterparty", "amount", "date", "number", "organization", "bank_account", "currency", "purpose"):
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
    def _build_purchase_select(mapped: dict[str, str | None]) -> list[str]:
        out: list[str] = []
        for key in ("counterparty", "amount", "date", "number", "organization", "currency"):
            value = mapped.get(key)
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _build_document_select(mapped: dict[str, str | None]) -> list[str]:
        out: list[str] = []
        for key in ("counterparty", "amount", "date", "number", "status", "posted", "reference", "deletion_mark"):
            value = mapped.get(key)
            if value and value not in out:
                out.append(value)
        return out

    def _normalize_inventory_row(self, row: dict[str, Any], mapped: dict[str, str | None]) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        item_ref = pick("item")
        warehouse_ref = pick("warehouse")

        return {
            "item": self._resolve_reference_value(mapped.get("item"), item_ref),
            "item_ref": item_ref,
            "warehouse": self._resolve_reference_value(mapped.get("warehouse"), warehouse_ref),
            "warehouse_ref": warehouse_ref,
            "quantity": pick("quantity"),
            "amount": pick("amount"),
            "period": pick("period"),
            "raw": row,
        }

    def _normalize_payment_row(self, row: dict[str, Any], mapped: dict[str, str | None], direction: str | None) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        counterparty_ref = pick("counterparty")
        currency_ref = pick("currency")
        bank_account_ref = pick("bank_account")
        counterparty_info = self._resolve_counterparty_info(counterparty_ref)

        return {
            "direction": direction,
            "counterparty": counterparty_info.get("display") or self._resolve_reference_value(mapped.get("counterparty"), counterparty_ref),
            "counterparty_ref": counterparty_ref,
            "counterparty_bin_or_iin": counterparty_info.get("bin_or_iin"),
            "amount": pick("amount"),
            "date": pick("date"),
            "number": pick("number"),
            "organization": self._resolve_reference_value(mapped.get("organization"), pick("organization")),
            "bank_account": self._resolve_reference_value(mapped.get("bank_account"), bank_account_ref),
            "bank_account_ref": bank_account_ref,
            "currency": self._resolve_reference_value(mapped.get("currency"), currency_ref),
            "currency_ref": currency_ref,
            "purpose": pick("purpose"),
            "raw": row,
        }

    def _normalize_sales_row(self, row: dict[str, Any], mapped: dict[str, str | None]) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        counterparty_ref = pick("counterparty")
        organization_ref = pick("organization")
        currency_ref = pick("currency")
        counterparty_info = self._resolve_counterparty_info(counterparty_ref)

        return {
            "counterparty": counterparty_info.get("display") or self._resolve_reference_value(mapped.get("counterparty"), counterparty_ref),
            "counterparty_ref": counterparty_ref,
            "counterparty_bin_or_iin": counterparty_info.get("bin_or_iin"),
            "amount": pick("amount"),
            "date": pick("date"),
            "number": pick("number"),
            "organization": self._resolve_reference_value(mapped.get("organization"), organization_ref),
            "organization_ref": organization_ref,
            "currency": self._resolve_reference_value(mapped.get("currency"), currency_ref),
            "currency_ref": currency_ref,
            "raw": row,
        }

    def _normalize_document_search_row(self, row: dict[str, Any], entity_name: str, mapped: dict[str, str | None]) -> dict[str, Any]:
        def pick(key: str) -> Any:
            field = mapped.get(key)
            return row.get(field) if field else None

        counterparty_ref = pick("counterparty")
        counterparty_info = self._resolve_counterparty_info(counterparty_ref)

        return {
            "document_type": entity_name,
            "number": pick("number"),
            "date": pick("date"),
            "counterparty": counterparty_info.get("display") or self._resolve_reference_value(mapped.get("counterparty"), counterparty_ref),
            "counterparty_ref": counterparty_ref,
            "amount": pick("amount"),
            "status": self._extract_document_status(row, mapped),
            "reference": pick("reference"),
        }

    def _extract_document_status(self, row: dict[str, Any], mapped: dict[str, str | None]) -> str | None:
        explicit_status = row.get(mapped["status"]) if mapped.get("status") else None
        if explicit_status not in (None, ""):
            return str(explicit_status)

        deletion_mark = self._to_bool_like(row.get(mapped["deletion_mark"])) if mapped.get("deletion_mark") else None
        if deletion_mark is True:
            return "marked_for_deletion"

        posted = self._to_bool_like(row.get(mapped["posted"])) if mapped.get("posted") else None
        if posted is True:
            return "posted"
        if posted is False:
            return "not_posted"
        return None

    def _resolve_reference_value(self, field_name: str | None, value: Any) -> Any:
        if not field_name or not self._is_guid_like(value):
            return value
        target_entity = self._reference_target_for_field(field_name)
        if not target_entity:
            return value
        preferred_fields = self._preferred_display_fields_for_entity(target_entity)
        resolved = self._fetch_entity_by_ref(target_entity, str(value), preferred_fields)
        if not resolved:
            return value
        for field in preferred_fields:
            resolved_value = resolved.get(field)
            if resolved_value not in (None, ""):
                return resolved_value
        return value

    def _resolve_counterparty_info(self, value: Any) -> dict[str, Any]:
        if not self._is_guid_like(value):
            return {"display": value, "bin_or_iin": None}
        resolved = self._fetch_entity_by_ref(
            "Catalog_Контрагенты",
            str(value),
            ("Description", "НаименованиеПолное", "ИдентификационныйКодЛичности", "РНН", "КодПоОКПО"),
        )
        if not resolved:
            return {"display": value, "bin_or_iin": None}
        display = resolved.get("Description") or resolved.get("НаименованиеПолное") or value
        bin_or_iin = (
            resolved.get("ИдентификационныйКодЛичности")
            or resolved.get("РНН")
            or resolved.get("КодПоОКПО")
        )
        return {"display": display, "bin_or_iin": bin_or_iin}

    def _fetch_entity_by_ref(self, entity_name: str, ref_key: str, select_fields: tuple[str, ...]) -> dict[str, Any] | None:
        cache_key = (entity_name, ref_key, tuple(select_fields))
        if cache_key in self._reference_cache:
            return self._reference_cache[cache_key]
        if not self._is_guid_like(ref_key) or ref_key == "00000000-0000-0000-0000-000000000000":
            self._reference_cache[cache_key] = None
            return None
        self._validate_identifier(entity_name, "entity_name")
        for field in select_fields:
            self._validate_identifier(field, "select field")
        path = f"{entity_name}(guid'{ref_key}')"
        response = self._get(path, params={"$select": ",".join(select_fields)}, headers={"Accept": "application/xml"})
        if response.status_code >= 400:
            self._reference_cache[cache_key] = None
            return None
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            self._reference_cache[cache_key] = None
            return None
        properties = None
        for node in root.iter():
            if self._xml_local_name(node.tag) == "properties":
                properties = node
                break
        if properties is None:
            self._reference_cache[cache_key] = None
            return None
        out: dict[str, Any] = {}
        for child in properties:
            local_name = self._xml_local_name(child.tag)
            if local_name in select_fields:
                out[local_name] = child.text
        self._reference_cache[cache_key] = out or None
        return self._reference_cache[cache_key]

    @staticmethod
    def _preferred_display_fields_for_entity(entity_name: str) -> tuple[str, ...]:
        if entity_name in {"Catalog_Склады", "Catalog_Кассы", "Catalog_Организации"}:
            return ("Description", "Code")
        if entity_name == "Catalog_БанковскиеСчета":
            return ("Description", "НомерСчета", "Code")
        if entity_name == "Catalog_Валюты":
            return ("Description", "БуквенныйКод", "НаименованиеПолное", "Code")
        return ("Description", "НаименованиеПолное", "Code")

    @staticmethod
    def _reference_target_for_field(field_name: str) -> str | None:
        normalized = OneCODataClient._norm(field_name)
        if "контрагент" in normalized:
            return "Catalog_Контрагенты"
        if "номенклатур" in normalized:
            return "Catalog_Номенклатура"
        if "склад" in normalized:
            return "Catalog_Склады"
        if "валют" in normalized:
            return "Catalog_Валюты"
        if "касс" in normalized:
            return "Catalog_Кассы"
        if "счетбанк" in normalized or "банковскиесчет" in normalized:
            return "Catalog_БанковскиеСчета"
        if "организац" in normalized:
            return "Catalog_Организации"
        return None

    @staticmethod
    def _is_guid_like(value: Any) -> bool:
        return isinstance(value, str) and bool(_GUID_RE.fullmatch(value))

    def _discover_document_search_candidates(self, document_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        requested_type = self._norm(document_type) if document_type else ""
        deduped: dict[str, dict[str, Any]] = {}
        for entity in self.list_entities():
            name = self._norm(entity.name)
            etype = self._norm(entity.entity_type)
            score = 0
            reasons: list[str] = []
            if "document" in name or "документ" in name or "document" in etype or "документ" in etype:
                score += 24
                reasons.append("match:document_entity")
            sales_score, sales_reasons = self._score_sales_entity(entity)
            payment_score, payment_reasons, _ = self._score_payment_entity(entity)
            if sales_score > 0:
                score += sales_score
                reasons.extend(sales_reasons)
            if payment_score > 0:
                score += payment_score
                reasons.extend(payment_reasons)
            if score <= 0:
                continue
            if requested_type and requested_type not in name and requested_type not in etype:
                continue

            mapped = self._map_document_fields([field.name for field in (entity.fields or [])])
            if not mapped.get("number"):
                continue

            candidate = {
                "entity": entity.name,
                "entity_type": entity.entity_type,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": sorted(set(reasons)),
                "mapped_fields": mapped,
            }
            current = deduped.get(entity.name)
            if current is None or candidate["score"] > current["score"]:
                deduped[entity.name] = candidate
        ranked = sorted(deduped.values(), key=lambda row: row["score"], reverse=True)
        if limit is None or limit <= 0:
            return ranked
        return ranked[:limit]

    @staticmethod
    def _document_search_candidate_limit(document_type: str | None, result_limit: int) -> int:
        if document_type and str(document_type).strip():
            return 6
        return min(max(result_limit * 2, 8), 12)

    def _safe_profile_discovery(
        self,
        label: str,
        loader: Callable[[], list[dict[str, Any]]],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        try:
            return loader()
        except Exception as exc:
            warnings.append(f"{label}: {type(exc).__name__}: {str(exc)[:200]}")
            return []

    def _build_document_search_filter(
        self,
        mapped: dict[str, str | None],
        *,
        document_number: str,
        date_from: str | None,
        date_to: str | None,
    ) -> str:
        parts: list[str] = []
        number_field = mapped.get("number")
        if number_field:
            escaped = self._escape_odata_string_literal(document_number)
            parts.append(f"substringof('{escaped}', {number_field}) eq true")
        date_field = mapped.get("date")
        if date_field and date_from:
            from_literal = self._to_odata_datetime_literal(date_from, end_of_day=False)
            if from_literal:
                parts.append(f"{date_field} ge {from_literal}")
        if date_field and date_to:
            to_literal = self._to_odata_datetime_literal(date_to, end_of_day=True)
            if to_literal:
                parts.append(f"{date_field} le {to_literal}")
        return " and ".join(parts)

    def _build_common_text_date_filter(
        self,
        mapped: dict[str, str | None],
        *,
        date_from: str | None,
        date_to: str | None,
        text_field_key: str,
        text_value: str | None,
    ) -> str:
        parts: list[str] = []
        date_field = mapped.get("date")
        if date_field and date_from:
            from_literal = self._to_odata_datetime_literal(date_from, end_of_day=False)
            if from_literal:
                parts.append(f"{date_field} ge {from_literal}")
        if date_field and date_to:
            to_literal = self._to_odata_datetime_literal(date_to, end_of_day=True)
            if to_literal:
                parts.append(f"{date_field} le {to_literal}")
        text_field = mapped.get(text_field_key)
        if text_field and text_value:
            escaped = self._escape_odata_string_literal(text_value.strip())
            if escaped:
                parts.append(f"substringof('{escaped}', {text_field}) eq true")
        return " and ".join(parts)

    def _classify_payment_account_type(self, entity_name: Any) -> str:
        haystack = self._norm(str(entity_name or ""))
        if any(term in haystack for term in ["касс", "cash", "кассовыйордер"]):
            return "cash"
        if any(term in haystack for term in ["банков", "bank", "расчетногосчета", "банковскогосчета", "платежноепоручение", "платежныйордер"]):
            return "bank"
        return "unknown"

    @staticmethod
    def _is_top_level_document_entity(entity_name: Any) -> bool:
        text = str(entity_name or "")
        return text.startswith("Document_") and text.count("_") == 1

    def _is_preferred_payment_source_entity(self, entity_name: Any) -> bool:
        text = str(entity_name or "")
        if not self._is_top_level_document_entity(text):
            return False
        haystack = self._norm(text)
        allowed_terms = [
            "платежноепоручение",
            "платежныйордер",
            "кассовыйордер",
            "списаниесбанковскогосчета",
            "поступлениенабанковскийсчет",
            "оплатаотпокупателяплатежнойкартой",
        ]
        blocked_terms = [
            "обменсбанками",
            "пакетобмен",
            "письмообмен",
            "сообщениеобмен",
            "счетфактура",
            "доверенность",
        ]
        if any(term in haystack for term in blocked_terms):
            return False
        return any(term in haystack for term in allowed_terms)

    @staticmethod
    def _escape_odata_string_literal(value: str) -> str:
        return str(value).replace("'", "''")

    def _to_odata_datetime_literal(self, value: str, *, end_of_day: bool) -> str | None:
        parsed = self._parse_date_like(value)
        if parsed is None:
            return None
        time_part = "23:59:59" if end_of_day else "00:00:00"
        return f"datetime'{parsed.isoformat()}T{time_part}'"

    def _empty_document_search_result(
        self,
        *,
        needle: str,
        document_type: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "document_number": needle,
            "document_type_filter": document_type,
            "filters_applied_in_python": {
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
            "matched_entities": [],
            "count_returned": 0,
            "data": [],
            "warnings": warnings or [],
            "note": "Поиск выполнен через безопасный read-only wrapper поверх document-like OData сущностей без raw OData для агента.",
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
            customer_rows = [row for row in [*sales_rows, *payment_rows] if str(row.get("counterparty") or "<unknown>") == customer]
            customer_bin_or_iin = next(
                (row.get("counterparty_bin_or_iin") for row in customer_rows if row.get("counterparty_bin_or_iin")),
                None,
            )
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
                "counterparty_bin_or_iin": customer_bin_or_iin,
                "as_of": as_of.isoformat(),
            }
        return settlement

    def _purchase_invoice_key(self, invoice: dict[str, Any]) -> tuple[str, str | None, str]:
        invoice_number = str(invoice.get("invoice_number") or invoice.get("number") or "")
        invoice_date = invoice.get("invoice_date")
        if isinstance(invoice_date, date):
            invoice_date_iso = invoice_date.isoformat()
        else:
            parsed = self._parse_date_like(invoice.get("date"))
            invoice_date_iso = parsed.isoformat() if parsed else None
        amount = self._to_decimal(invoice.get("amount"), default=Decimal("0")) or Decimal("0")
        return (invoice_number, invoice_date_iso, str(amount))

    def _summarize_purchase_document_sections(self, raw: dict[str, Any], max_lines: int = 5) -> dict[str, Any]:
        sections = {
            "Товары": "goods",
            "Услуги": "services",
            "ОС": "fixed_assets",
            "НМА": "intangibles",
        }
        section_counts: dict[str, int] = {}
        line_items_sample: list[dict[str, Any]] = []
        for source_name, public_name in sections.items():
            rows = raw.get(source_name)
            if not isinstance(rows, list) or not rows:
                continue
            section_counts[public_name] = len(rows)
            for row in rows:
                if len(line_items_sample) >= max_lines:
                    break
                name = (
                    row.get("Содержание")
                    or row.get("Description")
                    or self._resolve_reference_value("Номенклатура_Key", row.get("Номенклатура_Key"))
                    or self._resolve_reference_value("Номенклатура", row.get("Номенклатура"))
                )
                line_items_sample.append(
                    {
                        "section": public_name,
                        "name": name,
                        "quantity": row.get("Количество"),
                        "amount": row.get("Сумма"),
                    }
                )
        line_summary_parts = [f"{section}={count}" for section, count in section_counts.items()]
        return {
            "section_counts": section_counts,
            "line_items_sample": line_items_sample,
            "line_summary_text": ", ".join(line_summary_parts) if line_summary_parts else None,
        }

    def _summarize_supplier_reconciliation_document(
        self,
        raw: dict[str, Any],
        *,
        counterparty_display: str,
        bin_or_iin: Any,
        sample_lines_limit: int,
    ) -> dict[str, Any] | None:
        org_rows = raw.get("ПоДаннымОрганизации")
        if not isinstance(org_rows, list) or not org_rows:
            return None

        purchase_like = {"поступлениетоваровуслуг", "документрасчетовсконтрагентом", "корректировкадолга"}
        outgoing_payment_like = {
            "платежноепоручениеисходящее",
            "платежныйордерсписаниеденежныхсредств",
            "списаниесбанковскогосчета",
            "расходныйкассовыйордер",
        }

        purchase_rows: list[dict[str, Any]] = []
        payment_rows: list[dict[str, Any]] = []
        sample_rows: list[dict[str, Any]] = []
        doc_types_seen: set[str] = set()
        debit_total = Decimal("0")
        credit_total = Decimal("0")

        for row in org_rows:
            doc_type = str(row.get("Документ_Type") or "")
            normalized_doc_type = self._norm(doc_type.split(".")[-1] if "." in doc_type else doc_type)
            debit = self._to_decimal(row.get("Дебет"), default=Decimal("0")) or Decimal("0")
            credit = self._to_decimal(row.get("Кредит"), default=Decimal("0")) or Decimal("0")
            debit_total += debit
            credit_total += credit
            if doc_type:
                doc_types_seen.add(doc_type)
            if any(term in normalized_doc_type for term in purchase_like):
                purchase_rows.append(row)
            if any(term in normalized_doc_type for term in outgoing_payment_like) or "списани" in normalized_doc_type or "платеж" in normalized_doc_type:
                payment_rows.append(row)
            if len(sample_rows) < sample_lines_limit:
                sample_rows.append(
                    {
                        "date": row.get("Дата"),
                        "document_type": doc_type,
                        "debit": row.get("Дебет"),
                        "credit": row.get("Кредит"),
                    }
                )

        if not purchase_rows and not payment_rows:
            return None

        opening_balance = self._to_decimal(raw.get("ОстатокНаНачало"), default=Decimal("0")) or Decimal("0")
        discrepancy = self._to_decimal(raw.get("Расхождение"), default=Decimal("0")) or Decimal("0")
        balance_estimate = opening_balance + credit_total - debit_total

        return {
            "counterparty": counterparty_display,
            "bin_or_iin": bin_or_iin,
            "reconciliation_number": raw.get("Number"),
            "reconciliation_date": raw.get("Date"),
            "period_from": raw.get("ДатаНачала"),
            "period_to": raw.get("ДатаОкончания"),
            "organization": self._resolve_reference_value("Организация_Key", raw.get("Организация_Key")),
            "opening_balance": str(opening_balance),
            "discrepancy": str(discrepancy),
            "is_agreed": self._to_bool_like(raw.get("СверкаСогласована")),
            "purchase_document_count": len(purchase_rows),
            "outgoing_payment_count": len(payment_rows),
            "purchase_amount_total": str(sum((self._to_decimal(item.get("Кредит"), default=Decimal("0")) or Decimal("0") for item in purchase_rows), Decimal("0"))),
            "outgoing_payment_amount_total": str(sum((self._to_decimal(item.get("Дебет"), default=Decimal("0")) or Decimal("0") for item in payment_rows), Decimal("0"))),
            "balance_estimate_by_organization_view": str(balance_estimate),
            "document_types_seen": sorted(doc_types_seen),
            "organization_view_lines_sample": sample_rows,
            "source_entity": "Document_АктСверкиВзаиморасчетов",
        }

    def _extract_sales_line_items(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        rows = raw.get("Товары")
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            name = (
                row.get("Содержание")
                or row.get("Description")
                or self._resolve_reference_value("Номенклатура_Key", row.get("Номенклатура_Key"))
                or self._resolve_reference_value("Номенклатура", row.get("Номенклатура"))
            )
            out.append(
                {
                    "name": name,
                    "quantity": row.get("Количество"),
                    "amount": row.get("Сумма"),
                }
            )
        return out

    def _last_payment_dates_by_customer(self, payment_rows: list[dict[str, Any]]) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in payment_rows:
            customer = str(row.get("counterparty") or "<unknown>")
            row_date = self._parse_date_like(row.get("date"))
            if row_date is None:
                continue
            iso = row_date.isoformat()
            if customer not in out or iso > out[customer]:
                out[customer] = iso
        return out

    @staticmethod
    def _calculate_overdue_days(open_invoices: list[dict[str, Any]], as_of: date) -> int | None:
        open_dates = [
            invoice["invoice_date"]
            for invoice in open_invoices
            if invoice.get("outstanding_amount", Decimal("0")) > 0 and invoice.get("invoice_date") is not None
        ]
        if not open_dates:
            return None
        return (as_of - min(open_dates)).days

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
    def _decimal_to_text(value: Decimal) -> str:
        if value == value.to_integral():
            return str(value.quantize(Decimal("1")))
        normalized = value.normalize()
        return format(normalized, "f").rstrip("0").rstrip(".") if "." in format(normalized, "f") else str(normalized)

    @staticmethod
    def _severity_rank(value: Any) -> int:
        return {"critical": 0, "high": 1, "medium": 2}.get(str(value), 9)

    @staticmethod
    def _to_bool_like(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y", "да"}:
            return True
        if text in {"false", "0", "no", "n", "нет"}:
            return False
        return None

    def _parse_decimal_input(self, value: Any, *, field_name: str, default: Decimal | None = None) -> Decimal:
        if value is None or str(value).strip() == "":
            return default or Decimal("0")
        parsed = self._to_decimal(value, default=None)
        if parsed is None:
            raise ODataError(f"Некорректное числовое значение {field_name}: {value!r}.")
        return parsed

    def _validate_choice(self, value: str | None, *, allowed: set[str], default: str, field_name: str) -> str:
        if value is None or not str(value).strip():
            return default
        normalized = str(value).strip().lower()
        if normalized not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ODataError(f"Недопустимое значение {field_name}: {value!r}. Используйте: {allowed_text}.")
        return normalized

    def _validate_date_range(self, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
        parsed_from = self._parse_date_like(date_from) if date_from else None
        parsed_to = self._parse_date_like(date_to) if date_to else None
        if date_from and parsed_from is None:
            raise ODataError(f"Некорректная дата date_from: {date_from!r}. Используйте YYYY-MM-DD.")
        if date_to and parsed_to is None:
            raise ODataError(f"Некорректная дата date_to: {date_to!r}. Используйте YYYY-MM-DD.")
        if parsed_from and parsed_to and parsed_from > parsed_to:
            raise ODataError("date_from не может быть позже date_to.")
        return parsed_from.isoformat() if parsed_from else None, parsed_to.isoformat() if parsed_to else None

    @staticmethod
    def _text_match(value: Any, needle: str) -> bool:
        if value is None:
            return False
        return needle.lower() in str(value).lower()

    @staticmethod
    def _normalize_payment_direction(value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        direction = (value or "").strip().lower()
        if direction in {"outgoing", "payment_out", "paid", "expense", "расход", "исходящий", "out"}:
            return "outgoing"
        if direction in {"incoming", "payment_in", "received", "income", "приход", "входящий", "in"}:
            return "incoming"
        raise ODataError(f"Недопустимое направление платежа: {value!r}. Используйте incoming или outgoing.")

    @staticmethod
    def _xml_local_name(tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        return tag

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

    @staticmethod
    def _is_unsupported_where_filter_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "операция не разрешена в предложении" in text
            or "\"где\"" in text
            or "autoorder" in text
            or "ошибка при разборе опции запроса $filter" in text
        )

    @staticmethod
    def _is_access_denied_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "доступ запрещен" in text or "http 401" in text or "\"code\": \"20\"" in text
