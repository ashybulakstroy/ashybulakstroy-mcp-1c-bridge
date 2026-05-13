from __future__ import annotations

import logging
import re
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlparse

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
        self._account_label_cache: dict[str, str | None] = {}

    def _require_url(self) -> None:
        if not self.settings.odata_url:
            raise ODataError("ONEC_ODATA_URL не задан. Заполните .env или переменные окружения.")

    def _url(self, path: str) -> str:
        self._require_url()
        return f"{self.settings.odata_url}/{path.lstrip('/')}"

    def check_endpoint_health(self, *, check_metadata: bool = False) -> dict[str, Any]:
        self._require_url()
        host, port = self._get_endpoint_host_port()
        diagnosis = self._diagnose_endpoint_connectivity(host, port)
        result: dict[str, Any] = {
            "host": host,
            "port": port,
            "host_resolvable": diagnosis["host_resolved"],
            "tcp_reachable": diagnosis["tcp_reachable"],
            "server_alive": bool(diagnosis["host_resolved"] and diagnosis["tcp_reachable"]),
            "odata_reachable": None,
            "metadata_readable": None,
            "details": None,
        }
        if not check_metadata:
            return result
        if not result["server_alive"]:
            result["odata_reachable"] = False
            result["metadata_readable"] = False
            result["details"] = "OData metadata check skipped because host or port is unreachable."
            return result
        try:
            response = self._get("$metadata", headers={"Accept": "application/xml"})
            is_ok = response.status_code < 400
            result["odata_reachable"] = is_ok
            result["metadata_readable"] = is_ok
            result["details"] = f"HTTP {response.status_code}"
            return result
        except Exception as exc:
            result["odata_reachable"] = False
            result["metadata_readable"] = False
            result["details"] = str(exc)[:300]
            return result

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

    def _find_last_nonempty_skip(
        self,
        entity_name: str,
        *,
        select: list[str] | None = None,
        page_size: int,
        max_probe_skip: int,
    ) -> int:
        """Find the latest non-empty skip window without trusting OData sort support.

        Some 1C publications reject $filter/$orderby for document dates and expose
        old rows on the first page. This helper probes later pages with top=1 and
        returns the latest skip that still responds with at least one row.
        """
        last_good = 0
        probe = page_size
        upper_bound = max_probe_skip + page_size

        while probe <= max_probe_skip:
            try:
                payload = self.query_entity(entity_name, top=1, select=select or None, skip=probe)
            except ODataError:
                upper_bound = probe
                break
            if not (payload.get("data") or []):
                upper_bound = probe
                break
            last_good = probe
            probe *= 2
        else:
            upper_bound = max_probe_skip + page_size

        low = last_good
        high = upper_bound
        while low + page_size < high:
            mid_pages = ((low + high) // 2) // page_size
            mid = mid_pages * page_size
            if mid <= low:
                break
            try:
                payload = self.query_entity(entity_name, top=1, select=select or None, skip=mid)
            except ODataError:
                high = mid
                continue
            if payload.get("data") or []:
                low = mid
            else:
                high = mid
        return low

    def _read_recent_tail_rows(
        self,
        entity_name: str,
        *,
        select: list[str] | None = None,
        page_size: int,
        tail_pages: int,
        max_probe_skip: int,
        warnings: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read the most recent accessible page window for large document entities."""
        last_skip = self._find_last_nonempty_skip(
            entity_name,
            select=select,
            page_size=page_size,
            max_probe_skip=max_probe_skip,
        )
        rows: list[dict[str, Any]] = []
        start_skip = max(0, last_skip - page_size * max(tail_pages - 1, 0))
        for skip in range(start_skip, last_skip + 1, page_size):
            try:
                payload = self.query_entity(entity_name, top=page_size, select=select or None, skip=skip)
            except ODataError as exc:
                if warnings is not None:
                    warnings.append(
                        f"Tail paging for {entity_name} stopped at skip={skip}: {str(exc)[:160]}"
                    )
                break
            data = payload.get("data") or []
            if not data:
                break
            rows.extend(data)
            if len(data) < page_size and skip >= last_skip:
                break
        return rows

    def _load_document_source_rows(
        self,
        entity_name: str,
        *,
        select: list[str] | None,
        filter_expr: str | None,
        orderby: str | None,
        limit: int,
        page_size: int,
        tail_pages: int,
        max_probe_skip: int,
        warnings: list[str],
        prefer_recent_tail: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Load rows for one document-like source with safe fallback for slow 1C OData."""
        if prefer_recent_tail and not filter_expr and orderby:
            rows = self._read_recent_tail_rows(
                entity_name,
                select=select,
                page_size=page_size,
                tail_pages=tail_pages,
                max_probe_skip=max_probe_skip,
                warnings=warnings,
            )
            if rows:
                return rows, True
        try:
            raw = self.query_entity(
                entity_name,
                top=page_size,
                select=select or None,
                filter_expr=filter_expr or None,
                orderby=orderby or None,
            )
            rows = raw.get("data") or []
            if rows:
                return rows, False
        except ODataError as exc:
            unsupported = filter_expr and self._is_unsupported_where_filter_error(exc)
            if not unsupported:
                raise
            warnings.append(
                f"OData provider rejected pushdown filter for {entity_name}. "
                "Trying bounded tail paging with Python-side filtering."
            )

        tail_rows = self._read_recent_tail_rows(
            entity_name,
            select=select,
            page_size=page_size,
            tail_pages=tail_pages,
            max_probe_skip=max_probe_skip,
            warnings=warnings,
        )
        if not tail_rows and warnings:
            last_warning = warnings[-1]
            if entity_name in last_warning and ("Доступ запрещен" in last_warning or "401" in last_warning):
                warnings.append(
                    f"Источник {entity_name} пропущен: bounded fallback read is not accessible for this entity in current 1C publication."
                )
        return tail_rows, True

    def _select_primary_purchase_receipt_source(self, *, limit: int = 5) -> dict[str, Any] | None:
        sources = self.discover_purchase_sources(limit=limit, check_data=True)
        if not sources:
            return None
        preferred_terms = (
            "поступлениетоваровуслуг",
            "поступлениедопрасходов",
            "поступлениеизпереработки",
            "поступлениенма",
        )
        for source in sources:
            entity_name = self._norm(str(source.get("entity") or ""))
            if any(term in entity_name for term in preferred_terms):
                return source
        return sources[0]

    def _get(self, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        started = perf_counter()
        error: str | None = None
        response: httpx.Response | None = None
        try:
            response = self.client.get(self._url(path), params=params, headers=headers)
            return response
        except httpx.TimeoutException as exc:
            error = self._build_connectivity_message(exc)
            raise ODataError(error) from exc
        except httpx.RequestError as exc:
            error = self._build_connectivity_message(exc)
            raise ODataError(error) from exc
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

    def _build_connectivity_message(self, exc: Exception) -> str:
        host, port = self._get_endpoint_host_port()
        diagnosis = self._diagnose_endpoint_connectivity(host, port)
        prefix = f"OData endpoint недоступен: {host}:{port}."
        if isinstance(exc, httpx.TimeoutException):
            if diagnosis["host_resolved"] and diagnosis["tcp_reachable"]:
                return (
                    f"{prefix} Хост живой, но служба 1С OData не ответила за "
                    f"{self.settings.timeout_seconds} сек. Сервер перегружен, завис или OData-публикация отвечает слишком медленно."
                )
            if diagnosis["host_resolved"] and not diagnosis["tcp_reachable"]:
                return f"{prefix} Хост найден, но порт сервера недоступен. Проверьте, запущена ли публикация 1С и доступен ли сервер по сети."
            if not diagnosis["host_resolved"]:
                return f"{prefix} Не удалось определить адрес сервера. Проверьте адрес в ONEC_ODATA_URL и доступность DNS/сети."
            return f"{prefix} Сервер не ответил в срок. Проверьте доступность 1С и сети."
        if diagnosis["host_resolved"] and not diagnosis["tcp_reachable"]:
            return f"{prefix} Хост найден, но сетевое подключение к серверу не устанавливается. Проверьте публикацию 1С и доступность порта."
        if not diagnosis["host_resolved"]:
            return f"{prefix} Не удалось определить адрес сервера. Проверьте адрес в ONEC_ODATA_URL и доступность сети."
        return f"{prefix} Ошибка сетевого доступа к OData-службе 1С. Проверьте состояние сервера и публикации."

    def _get_endpoint_host_port(self) -> tuple[str, int]:
        parsed = urlparse(self.settings.odata_url or "")
        host = parsed.hostname or "unknown-host"
        if parsed.port:
            port = parsed.port
        elif parsed.scheme == "https":
            port = 443
        else:
            port = 80
        return host, port

    def _diagnose_endpoint_connectivity(self, host: str, port: int) -> dict[str, bool]:
        host_resolved = self._can_resolve_host(host)
        tcp_reachable = host_resolved and self._can_connect_tcp(host, port)
        return {
            "host_resolved": host_resolved,
            "tcp_reachable": tcp_reachable,
        }

    @staticmethod
    def _can_resolve_host(host: str) -> bool:
        try:
            socket.getaddrinfo(host, None)
            return True
        except OSError:
            return False

    def _can_connect_tcp(self, host: str, port: int) -> bool:
        timeout = max(1.0, min(float(self.settings.timeout_seconds), 3.0))
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

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
        warnings: list[str] = []
        if entity_name:
            entity = self.describe_entity(entity_name)
            if entity is None:
                raise ODataError(f"Сущность не найдена: {entity_name}")
            score, reasons = self._score_sales_entity(entity)
            mapped = self._map_sales_fields([f.name for f in (entity.fields or [])])
            source_candidates = [{
                "entity": entity.name,
                "score": score,
                "confidence": self._confidence_from_score(score),
                "reasons": reasons,
                "mapped_fields": mapped,
            }]
        else:
            source_candidates = self.discover_sales_sources(limit=3, check_data=True)
            if not source_candidates:
                raise ODataError("Не найден кандидат на источник реализаций/счетов. Запустите discover_sales_sources для диагностики.")
        effective_from = date or date_from
        effective_to = date or date_to
        query_top = min(max(limit * 5, 100), self.settings.max_top)
        page_size = min(max(limit * 20, 250), self.settings.max_top)
        normalized: list[dict[str, Any]] = []
        source = source_candidates[0]
        source_entities_used: list[str] = []
        first_source_with_rows: dict[str, Any] | None = None

        for candidate in source_candidates:
            mapped = candidate.get("mapped_fields") or {}
            select = None if include_sections else self._build_sales_select(mapped)
            filter_expr = self._build_common_text_date_filter(
                mapped,
                date_from=effective_from,
                date_to=effective_to,
                text_field_key="counterparty",
                text_value=counterparty,
            )
            orderby = f"{mapped['date']} desc" if mapped.get("date") else None
            rows, filter_fallback_used = self._load_document_source_rows(
                candidate["entity"],
                select=select,
                filter_expr=filter_expr,
                orderby=orderby,
                limit=limit,
                page_size=page_size,
                tail_pages=max(2, min(6, (limit // 5) + 2)),
                max_probe_skip=min(self.settings.max_top * 100, 50000),
                warnings=warnings,
                prefer_recent_tail=not bool(effective_from or effective_to or counterparty),
            )
            candidate_normalized = [self._normalize_sales_row(r, mapped) for r in rows]
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
            if not candidate_normalized:
                continue
            source_entities_used.append(str(candidate.get("entity")))
            normalized.extend(candidate_normalized[:query_top])
            if first_source_with_rows is None:
                first_source_with_rows = candidate
            source = candidate
            break

        normalized.sort(
            key=lambda r: (
                self._parse_datetime_like(r.get("date")) or datetime.min,
                self._to_decimal(r.get("amount"), default=Decimal("0")) or Decimal("0"),
            ),
            reverse=True,
        )
        deduped: list[dict[str, Any]] = []
        seen_keys: set[tuple[Any, Any, Any]] = set()
        for row in normalized:
            dedupe_key = (row.get("reference"), row.get("number"), row.get("date"))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            deduped.append(row)
        normalized = deduped

        if first_source_with_rows is not None:
            source = first_source_with_rows
        mapped = source.get("mapped_fields") or {}
        if not source_entities_used:
            warnings.append("В текущей OData-публикации не найдено строк по проверенным sales-like safe sources для заданных фильтров.")
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
            "source_entities_used": source_entities_used,
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
        sales_item_key_by_item: dict[str, str] = {}
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
                item_key = str(line.get("item_key") or "").strip()
                if item_key and item_name not in sales_item_key_by_item:
                    sales_item_key_by_item[item_name] = item_key

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

        candidate_rows = rows[: min(max(effective_limit * 3, 20), len(rows))]
        candidate_items = {str(row.get("item") or "").strip() for row in candidate_rows if str(row.get("item") or "").strip()}
        purchase_source: str | None = None
        purchase_warnings: list[str] = []
        supplier_by_item: dict[str, dict[str, Any]] = {}
        if candidate_items:
            item_meta_by_key: dict[str, dict[str, Any] | None] = {}
            for item_name in candidate_items:
                item_key = sales_item_key_by_item.get(item_name)
                if not item_key:
                    continue
                item_meta_by_key[item_key] = self._fetch_entity_by_ref(
                    "Catalog_Номенклатура",
                    item_key,
                    ("Description", "Parent_Key", "НоменклатурнаяГруппа_Key"),
                )
            purchase_window_start = inferred_as_of - timedelta(days=365)
            purchase_probe_limit = min(max(len(candidate_items) * 20, 200), self.settings.max_top)
            try:
                purchase_receipt_source = self._select_primary_purchase_receipt_source(limit=5)
                purchases = self.get_purchase_documents(
                    date_from=purchase_window_start.isoformat(),
                    date_to=inferred_as_of.isoformat(),
                    limit=purchase_probe_limit,
                    entity_name=(purchase_receipt_source or {}).get("entity"),
                    include_sections=True,
                )
                purchase_source = (purchases.get("source") or {}).get("entity")
                purchase_warnings.extend(list(purchases.get("warnings") or []))
                purchase_rows = sorted(
                    purchases.get("data") or [],
                    key=lambda row: self._parse_date_like(row.get("date")) or date.min,
                    reverse=True,
                )
                suppliers_by_parent: dict[str, dict[str, Any]] = {}
                suppliers_by_group: dict[str, dict[str, Any]] = {}
                for purchase_row in purchase_rows:
                    supplier_name = purchase_row.get("counterparty")
                    if not supplier_name:
                        continue
                    raw = purchase_row.get("raw") or {}
                    for line in self._extract_purchase_line_items(raw):
                        item_name = str(line.get("name") or "").strip()
                        item_key = str(line.get("item_key") or "").strip()
                        if item_name and item_name in candidate_items and item_name not in supplier_by_item:
                            supplier_by_item[item_name] = {
                                "preferred_supplier": supplier_name,
                                "supplier_last_purchase_date": purchase_row.get("date"),
                                "supplier_last_purchase_document_number": purchase_row.get("number"),
                                "supplier_match_method": "exact_item_name",
                                "supplier_match_confidence": "high",
                                "supplier_candidates": [
                                    {
                                        "supplier": supplier_name,
                                        "match_method": "exact_item_name",
                                        "match_confidence": "high",
                                        "evidence_count": 1,
                                        "last_purchase_date": purchase_row.get("date"),
                                        "last_purchase_document_number": purchase_row.get("number"),
                                    }
                                ],
                            }
                        if item_key:
                            meta = item_meta_by_key.get(item_key)
                            if meta is None:
                                meta = self._fetch_entity_by_ref(
                                    "Catalog_Номенклатура",
                                    item_key,
                                    ("Description", "Parent_Key", "НоменклатурнаяГруппа_Key"),
                                )
                                item_meta_by_key[item_key] = meta
                            if meta:
                                parent_key = str(meta.get("Parent_Key") or "")
                                group_key = str(meta.get("НоменклатурнаяГруппа_Key") or "")
                                event = {
                                    "supplier": supplier_name,
                                    "date": purchase_row.get("date"),
                                    "document_number": purchase_row.get("number"),
                                }
                                if parent_key and parent_key != "00000000-0000-0000-0000-000000000000":
                                    bucket = suppliers_by_parent.setdefault(parent_key, {})
                                    bucket.setdefault(supplier_name, event)
                                if group_key and group_key != "00000000-0000-0000-0000-000000000000":
                                    bucket = suppliers_by_group.setdefault(group_key, {})
                                    bucket.setdefault(supplier_name, event)

                parent_supplier_counts: dict[str, dict[str, int]] = {}
                group_supplier_counts: dict[str, dict[str, int]] = {}
                for purchase_row in purchase_rows:
                    supplier_name = purchase_row.get("counterparty")
                    if not supplier_name:
                        continue
                    raw = purchase_row.get("raw") or {}
                    for line in self._extract_purchase_line_items(raw):
                        item_key = str(line.get("item_key") or "").strip()
                        if not item_key:
                            continue
                        meta = item_meta_by_key.get(item_key)
                        if meta is None:
                            meta = self._fetch_entity_by_ref(
                                "Catalog_Номенклатура",
                                item_key,
                                ("Description", "Parent_Key", "НоменклатурнаяГруппа_Key"),
                            )
                            item_meta_by_key[item_key] = meta
                        if not meta:
                            continue
                        parent_key = str(meta.get("Parent_Key") or "")
                        group_key = str(meta.get("НоменклатурнаяГруппа_Key") or "")
                        if parent_key and parent_key != "00000000-0000-0000-0000-000000000000":
                            bucket = parent_supplier_counts.setdefault(parent_key, {})
                            bucket[supplier_name] = bucket.get(supplier_name, 0) + 1
                        if group_key and group_key != "00000000-0000-0000-0000-000000000000":
                            bucket = group_supplier_counts.setdefault(group_key, {})
                            bucket[supplier_name] = bucket.get(supplier_name, 0) + 1

                for item_name in candidate_items:
                    if item_name in supplier_by_item:
                        continue
                    sales_item_key = sales_item_key_by_item.get(item_name)
                    if not sales_item_key:
                        continue
                    sales_meta = item_meta_by_key.get(sales_item_key)
                    if not sales_meta:
                        continue
                    parent_key = str(sales_meta.get("Parent_Key") or "")
                    group_key = str(sales_meta.get("НоменклатурнаяГруппа_Key") or "")
                    parent_counts = parent_supplier_counts.get(parent_key, {})
                    group_counts = group_supplier_counts.get(group_key, {})
                    selected_supplier: str | None = None
                    selected_event: dict[str, Any] | None = None
                    match_method: str | None = None
                    confidence: str | None = None

                    if parent_counts:
                        ordered = sorted(parent_counts.items(), key=lambda pair: pair[1], reverse=True)
                        top_supplier, top_count = ordered[0]
                        second_count = ordered[1][1] if len(ordered) > 1 else 0
                        if top_count >= 3 and top_count > second_count:
                            selected_supplier = top_supplier
                            selected_event = (suppliers_by_parent.get(parent_key) or {}).get(top_supplier)
                            match_method = "parent_group_purchase_history"
                            confidence = "medium" if top_count >= max(second_count * 2, 4) else "low"
                    if selected_supplier is None and group_counts:
                        ordered = sorted(group_counts.items(), key=lambda pair: pair[1], reverse=True)
                        top_supplier, top_count = ordered[0]
                        second_count = ordered[1][1] if len(ordered) > 1 else 0
                        if top_count >= 5 and top_count > second_count:
                            selected_supplier = top_supplier
                            selected_event = (suppliers_by_group.get(group_key) or {}).get(top_supplier)
                            match_method = "nomenclature_group_purchase_history"
                            confidence = "low"

                    if selected_supplier is not None:
                        candidates: list[dict[str, Any]] = []
                        if match_method == "parent_group_purchase_history" and parent_counts:
                            for supplier_name, count in sorted(parent_counts.items(), key=lambda pair: pair[1], reverse=True)[:3]:
                                event = (suppliers_by_parent.get(parent_key) or {}).get(supplier_name)
                                candidates.append(
                                    {
                                        "supplier": supplier_name,
                                        "match_method": "parent_group_purchase_history",
                                        "match_confidence": "medium" if supplier_name == selected_supplier else "low",
                                        "evidence_count": count,
                                        "last_purchase_date": (event or {}).get("date"),
                                        "last_purchase_document_number": (event or {}).get("document_number"),
                                    }
                                )
                        elif match_method == "nomenclature_group_purchase_history" and group_counts:
                            for supplier_name, count in sorted(group_counts.items(), key=lambda pair: pair[1], reverse=True)[:3]:
                                event = (suppliers_by_group.get(group_key) or {}).get(supplier_name)
                                candidates.append(
                                    {
                                        "supplier": supplier_name,
                                        "match_method": "nomenclature_group_purchase_history",
                                        "match_confidence": "low",
                                        "evidence_count": count,
                                        "last_purchase_date": (event or {}).get("date"),
                                        "last_purchase_document_number": (event or {}).get("document_number"),
                                    }
                                )
                        supplier_by_item[item_name] = {
                            "preferred_supplier": selected_supplier,
                            "supplier_last_purchase_date": (selected_event or {}).get("date"),
                            "supplier_last_purchase_document_number": (selected_event or {}).get("document_number"),
                            "supplier_match_method": match_method,
                            "supplier_match_confidence": confidence,
                            "supplier_candidates": candidates,
                        }
            except Exception as exc:
                purchase_warnings.append(
                    f"Не удалось безопасно определить поставщика товара по published purchase documents: {str(exc)[:200]}"
                )

        warnings = list(inventory.get("warnings") or [])
        warnings.extend(sales.get("warnings") or [])
        warnings.extend(purchase_warnings)
        warnings.append(
            "Это read-only управленческая рекомендация закупа: продажи за период и текущий остаток из published OData. Это не официальный MRP-расчет 1С."
        )

        for row in rows:
            supplier_info = supplier_by_item.get(str(row.get("item") or "").strip()) or {}
            row["preferred_supplier"] = supplier_info.get("preferred_supplier")
            row["supplier_last_purchase_date"] = supplier_info.get("supplier_last_purchase_date")
            row["supplier_last_purchase_document_number"] = supplier_info.get("supplier_last_purchase_document_number")
            row["supplier_match_method"] = supplier_info.get("supplier_match_method")
            row["supplier_match_confidence"] = supplier_info.get("supplier_match_confidence")
            row["supplier_candidates"] = supplier_info.get("supplier_candidates") or []

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
                "purchase_source": purchase_source,
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
        effective_limit = min(max(int(limit), 1), 100)
        validated_from, validated_to = self._validate_date_range(date or date_from, date or date_to)
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
            sources = [source]
        else:
            sources = self.discover_purchase_sources(limit=5, check_data=True)
            if not sources:
                raise ODataError("Не найден кандидат на источник поступлений/счетов поставщика. Запустите discover_purchase_sources для диагностики.")

        warnings: list[str] = []
        normalized: list[dict[str, Any]] = []
        first_source_with_rows: dict[str, Any] | None = None
        source_entities_used: list[str] = []
        for source in sources:
            mapped = source.get("mapped_fields") or {}
            select = None if include_sections else self._build_purchase_select(mapped)
            filter_expr = self._build_common_text_date_filter(
                mapped,
                date_from=validated_from,
                date_to=validated_to,
                text_field_key="counterparty",
                text_value=counterparty,
            )
            rows, _tail_used = self._load_document_source_rows(
                source["entity"],
                select=select or None,
                filter_expr=filter_expr or None,
                orderby=f"{mapped['date']} desc" if mapped.get("date") else None,
                limit=min(max(effective_limit * 3, 100), self.settings.max_top),
                page_size=min(max(effective_limit * 3, 100), self.settings.max_top),
                tail_pages=3,
                max_probe_skip=min(self.settings.max_top * 100, 50000),
                warnings=warnings,
                prefer_recent_tail=True,
            )
            if not rows:
                continue
            if first_source_with_rows is None:
                first_source_with_rows = source
            source_entities_used.append(source["entity"])
            for row in rows:
                item = self._normalize_sales_row(row, mapped)
                if (validated_from or validated_to) and not self._date_in_range(item.get("date"), validated_from, validated_to):
                    continue
                if counterparty and not (
                    self._text_match(item.get("counterparty"), counterparty) or self._text_match(item.get("raw"), counterparty)
                ):
                    continue
                normalized.append(item)

        source = first_source_with_rows or (sources[0] if sources else None)
        mapped = (source or {}).get("mapped_fields") or {}
        if not mapped.get("counterparty"):
            warnings.append("Не найдено явное поле поставщика/контрагента в источнике поступлений.")
        if not mapped.get("amount"):
            warnings.append("Не найдено явное поле суммы в источнике поступлений.")
        if not mapped.get("date"):
            warnings.append("Не найдено явное поле даты в источнике поступлений.")

        normalized.sort(
            key=lambda item: (
                self._parse_datetime_like(item.get("date")) or datetime.min,
                str(item.get("number") or ""),
                str(item.get("counterparty") or ""),
            ),
            reverse=True,
        )
        deduped: list[dict[str, Any]] = []
        seen_purchase_rows: set[tuple[str, str, str]] = set()
        for row in normalized:
            row_key = (
                str(row.get("reference") or ""),
                str(row.get("number") or ""),
                str(row.get("date") or ""),
            )
            if row_key in seen_purchase_rows:
                continue
            seen_purchase_rows.add(row_key)
            deduped.append(row)
        normalized = deduped

        total_amount = Decimal("0")
        for row in normalized[:effective_limit]:
            amount = self._to_decimal(row.get("amount"), default=None)
            if amount is not None:
                total_amount += amount

        return {
            "source": source,
            "source_entities_used": source_entities_used,
            "filters_applied_in_python": {
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
                "counterparty": counterparty,
            },
            "count_returned": min(len(normalized), effective_limit),
            "total_amount": str(total_amount),
            "data": normalized[:effective_limit],
            "warnings": warnings,
            "note": "Поступления/счета поставщика определены по metadata-эвристике OData. Для точного учета кредиторки сверяйте с официальными отчетами 1С.",
        }

    def get_purchase_document_details(
        self,
        document_number: str,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        max_lines: int = 100,
    ) -> dict[str, Any]:
        """Return safe header + line details for one supplier purchase document."""
        needle = str(document_number or "").strip()
        if not needle:
            raise ODataError("document_number не должен быть пустым.")

        effective_lines = min(max(int(max_lines), 1), 200)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        search = self.search_document_by_number(
            document_number=needle,
            document_type="Поступление",
            date_from=validated_from,
            date_to=validated_to,
            limit=10,
        )
        candidates = [
            row for row in (search.get("data") or [])
            if str(row.get("document_type") or "") == "Document_ПоступлениеТоваровУслуг"
            and self._document_number_matches(str(row.get("number") or ""), needle)
            and (not counterparty_name or self._text_match(row.get("counterparty"), counterparty_name))
        ]
        if not candidates:
            return {
                "document_number": needle,
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "max_lines": effective_lines,
                },
                "warnings": list(search.get("warnings") or []),
                "note": "Документ поступления не найден в опубликованном read-only OData-контуре 1С.",
            }

        header = candidates[0]
        header_date = self._parse_date_like(header.get("date"))
        detailed = self.get_purchase_documents(
            date_from=header_date.isoformat() if header_date else validated_from,
            date_to=header_date.isoformat() if header_date else validated_to,
            counterparty=header.get("counterparty"),
            limit=20,
            entity_name="Document_ПоступлениеТоваровУслуг",
            include_sections=True,
        )
        matched_row = next(
            (
                row for row in (detailed.get("data") or [])
                if self._document_number_matches(str(row.get("number") or ""), needle)
                and (
                    not counterparty_name
                    or self._text_match(row.get("counterparty"), counterparty_name)
                )
            ),
            None,
        )
        if matched_row is None:
            return {
                "document_number": needle,
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "max_lines": effective_lines,
                },
                "warnings": list(search.get("warnings") or []) + list(detailed.get("warnings") or []),
                "note": "Шапка документа найдена, но детальные строки поступления не удалось безопасно прочитать из OData.",
            }

        raw = matched_row.get("raw") or {}
        lines: list[dict[str, Any]] = []
        for section_name, public_name in (
            ("Товары", "goods"),
            ("Услуги", "services"),
            ("ОС", "fixed_assets"),
            ("НМА", "intangibles"),
        ):
            section_rows = raw.get(section_name)
            if not isinstance(section_rows, list):
                continue
            for row in section_rows:
                name = (
                    row.get("Содержание")
                    or row.get("Description")
                    or self._resolve_reference_value("Номенклатура_Key", row.get("Номенклатура_Key"))
                    or self._resolve_reference_value("Номенклатура", row.get("Номенклатура"))
                )
                lines.append(
                    {
                        "section": public_name,
                        "name": name,
                        "item_key": row.get("Номенклатура_Key"),
                        "quantity": row.get("Количество"),
                        "price": row.get("Цена"),
                        "amount": row.get("Сумма"),
                        "accounting_account": (
                            row.get("СчетУчетаБУ_Key")
                            or row.get("СчетУчетаБУ")
                            or row.get("СчетУчета")
                        ),
                    }
                )

        section_summary = self._summarize_purchase_document_sections(raw, max_lines=min(effective_lines, 20))
        return {
            "document_number": needle,
            "count_returned": 1,
            "data": [
                {
                    "document_type": "Document_ПоступлениеТоваровУслуг",
                    "document_date": matched_row.get("date"),
                    "document_number": matched_row.get("number"),
                    "counterparty": matched_row.get("counterparty"),
                    "amount": matched_row.get("amount"),
                    "currency": matched_row.get("currency"),
                    "organization": matched_row.get("organization"),
                    "warehouse": self._resolve_reference_value("Склад_Key", raw.get("Склад_Key")),
                    "operation_type": raw.get("ВидОперации"),
                    "incoming_document_type": raw.get("ВидВходящегоДокумента"),
                    "incoming_document_number": raw.get("НомерВходящегоДокумента"),
                    "incoming_document_date": raw.get("ДатаВходящегоДокумента"),
                    "reference": matched_row.get("reference"),
                    "section_counts": section_summary["section_counts"],
                    "line_summary_text": section_summary["line_summary_text"],
                    "line_count": len(lines),
                    "lines": lines[:effective_lines],
                }
            ],
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "max_lines": effective_lines,
            },
            "source": {
                "entity": "Document_ПоступлениеТоваровУслуг",
                "confidence": "high",
            },
            "warnings": list(search.get("warnings") or []) + list(detailed.get("warnings") or []),
            "note": "Read-only details view of one published purchase document. Не выполняет запись в 1С и не раскрывает raw OData агенту.",
        }

    def get_purchase_receipts_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        item_name: str | None = None,
        limit: int = 50,
        items_per_document: int = 10,
    ) -> dict[str, Any]:
        """Return safe purchase receipts by period as flat business rows."""
        effective_limit = min(max(int(limit), 1), 100)
        sample_items_limit = min(max(int(items_per_document), 1), 30)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        purchase_receipt_source = self._select_primary_purchase_receipt_source(limit=5)
        if purchase_receipt_source is None:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "item_name": item_name,
                    "limit": effective_limit,
                    "items_per_document": sample_items_limit,
                },
                "warnings": [
                    "Не найден безопасный read-only источник поступлений ТМЗ/услуг в OData."
                ],
                "note": "Поступления не найдены в опубликованном OData-контуре 1С.",
            }

        receipts = self.get_purchase_documents(
            date_from=validated_from,
            date_to=validated_to,
            counterparty=counterparty_name,
            limit=min(max(effective_limit * 4, 100), self.settings.max_top),
            entity_name=purchase_receipt_source.get("entity"),
            include_sections=True,
        )
        document_rows: list[dict[str, Any]] = []
        item_filter = str(item_name or "").strip()
        for row in receipts.get("data") or []:
            raw = row.get("raw") or {}
            line_items = self._extract_purchase_line_items(raw)
            grouped_items: dict[str, dict[str, Any]] = {}
            for line in line_items:
                if item_filter and not self._text_match(line.get("name"), item_filter):
                    continue
                item_key = str(line.get("name") or "").strip()
                if not item_key:
                    continue
                bucket = grouped_items.setdefault(
                    item_key,
                    {
                        "item": item_key,
                        "quantity": 0,
                        "amount": 0,
                    },
                )
                quantity = self._safe_float(line.get("quantity"))
                amount = self._safe_float(line.get("amount"))
                if quantity is not None:
                    bucket["quantity"] += quantity
                if amount is not None:
                    bucket["amount"] += amount
            if item_filter and not grouped_items:
                continue
            normalized_items = sorted(
                grouped_items.values(),
                key=lambda item: (
                    -float(item.get("quantity") or 0),
                    str(item.get("item") or ""),
                ),
            )
            document_rows.append(
                {
                    "date": row.get("date"),
                    "date_only": str(row.get("date") or "")[:10],
                    "document_number": row.get("number"),
                    "supplier": row.get("counterparty"),
                    "document_amount": row.get("amount"),
                    "currency": row.get("currency"),
                    "item_count": len(normalized_items),
                    "items": normalized_items[:sample_items_limit],
                    "source_entity": purchase_receipt_source.get("entity"),
                }
            )

        document_rows.sort(
            key=lambda item: (
                self._parse_datetime_like(item.get("date")) or datetime.min,
                str(item.get("document_number") or ""),
            ),
            reverse=True,
        )
        document_rows = document_rows[:effective_limit]
        flat_rows: list[dict[str, Any]] = []
        for document in document_rows:
            for item in document.get("items") or []:
                flat_rows.append(
                    {
                        "date": document.get("date_only"),
                        "item": item.get("item"),
                        "quantity": item.get("quantity"),
                        "supplier": document.get("supplier"),
                        "document_number": document.get("document_number"),
                        "amount": item.get("amount"),
                        "currency": document.get("currency"),
                        "source_entity": document.get("source_entity"),
                    }
                )
        return {
            "count_returned": len(flat_rows),
            "document_count_returned": len(document_rows),
            "data": flat_rows,
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "item_name": item_name,
                "limit": effective_limit,
                "items_per_document": sample_items_limit,
            },
            "source": purchase_receipt_source,
            "warnings": list(receipts.get("warnings") or []),
            "note": "Read-only purchase receipts summary from published OData. Формат: дата, товар, объем, поставщик, номер документа.",
        }

    def get_sales_document_details(
        self,
        document_number: str,
        counterparty_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_lines: int = 50,
    ) -> dict[str, Any]:
        """Return safe read-only details for one sales document with line items."""
        effective_max_lines = min(max(int(max_lines), 1), 200)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        source_list = self.discover_sales_sources(limit=1, check_data=True)
        if not source_list:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "document_number": document_number,
                    "counterparty_name": counterparty_name,
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "max_lines": effective_max_lines,
                },
                "warnings": ["Не найден безопасный источник реализаций в OData."],
                "note": "Реализация не найдена в опубликованном read-only OData контуре.",
            }
        source = source_list[0]
        entity_name = str(source.get("entity") or "Document_РеализацияТоваровУслуг")
        mapped = source.get("mapped_fields") or {}
        warnings: list[str] = []
        candidates = self._get_recent_sales_headers(
            entity_name=entity_name,
            mapped=mapped,
            date_from=validated_from,
            date_to=validated_to,
            counterparty_name=counterparty_name,
            max_documents=200,
            warnings=warnings,
        )
        needle = str(document_number or "").strip().lstrip("0")
        candidates = [
            row for row in candidates
            if str(row.get("number") or "").strip().lstrip("0") == needle
        ]
        if not candidates:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "document_number": document_number,
                    "counterparty_name": counterparty_name,
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "max_lines": effective_max_lines,
                },
                "warnings": warnings,
                "note": "Реализация не найдена в опубликованном read-only OData контуре.",
            }
        detailed_header = candidates[0]
        raw = self._fetch_raw_entity_by_ref(entity_name, str(detailed_header.get("reference") or ""))
        if raw is None:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "document_number": document_number,
                    "counterparty_name": counterparty_name,
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "max_lines": effective_max_lines,
                },
                "warnings": warnings,
                "note": "Шапка реализации найдена, но детальные строки документа не были прочитаны из OData.",
            }
        detailed = self._normalize_sales_row(raw, mapped)
        line_items = self._extract_sales_line_items(raw)[:effective_max_lines]
        section_counts = {
            "goods": len(raw.get("Товары") or []) if isinstance(raw.get("Товары"), list) else 0,
            "services": len(raw.get("Услуги") or []) if isinstance(raw.get("Услуги"), list) else 0,
        }
        return {
            "count_returned": 1,
            "data": [
                {
                    "document_type": "Document_РеализацияТоваровУслуг",
                    "document_number": detailed.get("number"),
                    "date": detailed.get("date"),
                    "signed_date": self._extract_sales_signed_date(raw),
                    "counterparty": detailed.get("counterparty"),
                    "counterparty_bin_or_iin": detailed.get("counterparty_bin_or_iin"),
                    "organization": detailed.get("organization"),
                    "warehouse": self._extract_sales_warehouse(raw),
                    "structural_unit": self._extract_sales_structural_unit(raw, detailed.get("organization") or raw.get("Организация")),
                    "operation_type": raw.get("ВидОперации"),
                    "operation_type_display": self._format_sales_operation_type(raw),
                    "issue_method": raw.get("СпособВыпискиАктовВыполненныхРабот"),
                    "issue_method_display": self._format_enum_label(raw.get("СпособВыпискиАктовВыполненныхРабот")),
                    "invoice_number": self._extract_sales_invoice_number(raw),
                    "invoice_document": self._extract_sales_invoice_document(raw),
                    "settlement_document": self._extract_sales_settlement_document(raw),
                    "basis_document": self._extract_sales_basis_document(raw),
                    "responsible": self._resolve_reference_value("Ответственный_Key", raw.get("Ответственный_Key")),
                    "comment": raw.get("Комментарий"),
                    "amount": detailed.get("amount"),
                    "currency": detailed.get("currency"),
                    "status": self._extract_document_status(raw, self._map_document_fields(list(raw.keys()))),
                    "section_counts": section_counts,
                    "lines": line_items,
                    "source_entity": "Document_РеализацияТоваровУслуг",
                }
            ],
            "filters_applied_in_python": {
                "document_number": document_number,
                "counterparty_name": counterparty_name,
                "date_from": validated_from,
                "date_to": validated_to,
                "max_lines": effective_max_lines,
            },
            "source": source,
            "warnings": warnings,
            "note": "Read-only details view of one published sales document. Не выполняет запись в 1С и не раскрывает raw OData агенту.",
        }

    def get_sales_receipts_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        item_name: str | None = None,
        limit: int = 50,
        items_per_document: int = 10,
    ) -> dict[str, Any]:
        """Return safe sales rows by period as flat business rows."""
        effective_limit = min(max(int(limit), 1), 100)
        sample_items_limit = min(max(int(items_per_document), 1), 30)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        sales = self._get_recent_sales_documents(
            date_from=validated_from,
            date_to=validated_to,
            counterparty_name=counterparty_name,
            max_documents=min(max(effective_limit, 1), 30),
        )
        document_rows: list[dict[str, Any]] = []
        item_filter = str(item_name or "").strip()
        for row in sales.get("data") or []:
            raw = row.get("raw") or {}
            line_items = self._extract_sales_line_items(raw)
            grouped_items: dict[str, dict[str, Any]] = {}
            for line in line_items:
                if item_filter and not self._text_match(line.get("name"), item_filter):
                    continue
                item_key = str(line.get("name") or "").strip()
                if not item_key:
                    continue
                bucket = grouped_items.setdefault(
                    item_key,
                    {
                        "item": item_key,
                        "quantity": 0,
                        "amount": 0,
                    },
                )
                quantity = self._safe_float(line.get("quantity"))
                amount = self._safe_float(line.get("amount"))
                if quantity is not None:
                    bucket["quantity"] += quantity
                if amount is not None:
                    bucket["amount"] += amount
            if item_filter and not grouped_items:
                continue
            normalized_items = sorted(
                grouped_items.values(),
                key=lambda item: (-float(item.get("quantity") or 0), str(item.get("item") or "")),
            )
            document_rows.append(
                {
                    "date": row.get("date"),
                    "date_only": str(row.get("date") or "")[:10],
                    "document_number": row.get("number"),
                    "counterparty": row.get("counterparty"),
                    "amount": row.get("amount"),
                    "currency": row.get("currency"),
                    "warehouse": self._extract_sales_warehouse(raw),
                    "operation_type": raw.get("ВидОперации"),
                    "signed_date": self._extract_sales_signed_date(raw),
                    "issue_method": raw.get("СпособВыпискиАктовВыполненныхРабот"),
                    "item_count": len(normalized_items),
                    "items": normalized_items[:sample_items_limit],
                    "source_entity": "Document_РеализацияТоваровУслуг",
                }
            )

        document_rows.sort(
            key=lambda item: (
                self._parse_datetime_like(item.get("date")) or datetime.min,
                str(item.get("document_number") or ""),
            ),
            reverse=True,
        )
        document_rows = document_rows[:effective_limit]
        flat_rows: list[dict[str, Any]] = []
        for document in document_rows:
            for item in document.get("items") or []:
                flat_rows.append(
                    {
                        "date": document.get("date_only"),
                        "item": item.get("item"),
                        "quantity": item.get("quantity"),
                        "counterparty": document.get("counterparty"),
                        "document_number": document.get("document_number"),
                        "amount": item.get("amount"),
                        "currency": document.get("currency"),
                        "warehouse": document.get("warehouse"),
                        "operation_type": document.get("operation_type"),
                        "signed_date": document.get("signed_date"),
                        "issue_method": document.get("issue_method"),
                        "source_entity": document.get("source_entity"),
                    }
                )
        return {
            "count_returned": len(flat_rows),
            "document_count_returned": len(document_rows),
            "data": flat_rows,
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "item_name": item_name,
                "limit": effective_limit,
                "items_per_document": sample_items_limit,
            },
            "source": sales.get("source"),
            "warnings": list(sales.get("warnings") or []),
            "note": "Read-only sales receipts summary from published OData. Формат: дата, товар, объем, контрагент, номер документа.",
        }

    def get_sales_journal_view(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return screen-like sales journal rows close to the 1C list view."""
        effective_limit = min(max(int(limit), 1), 100)
        validated_from, validated_to = self._validate_date_range(date_from, date_to)
        source_list = self.discover_sales_sources(limit=1, check_data=True)
        if not source_list:
            return {
                "count_returned": 0,
                "data": [],
                "filters_applied_in_python": {
                    "date_from": validated_from,
                    "date_to": validated_to,
                    "counterparty_name": counterparty_name,
                    "limit": effective_limit,
                },
                "warnings": ["Не найден безопасный источник реализаций в OData."],
                "note": "Журнал реализаций не построен, потому что в OData не найден безопасный read-only источник продаж.",
            }

        source = source_list[0]
        entity_name = str(source.get("entity") or "Document_РеализацияТоваровУслуг")
        mapped = source.get("mapped_fields") or {}
        warnings: list[str] = []
        headers = self._get_recent_sales_headers(
            entity_name=entity_name,
            mapped=mapped,
            date_from=validated_from,
            date_to=validated_to,
            counterparty_name=counterparty_name,
            max_documents=effective_limit,
            warnings=warnings,
        )
        rows: list[dict[str, Any]] = []
        for header in headers:
            ref_key = str(header.get("reference") or "")
            raw = self._fetch_raw_entity_by_ref(entity_name, ref_key)
            if not raw:
                continue
            detailed = self._normalize_sales_row(raw, mapped)
            rows.append(
                {
                    "date": detailed.get("date"),
                    "date_only": str(detailed.get("date") or "")[:10],
                    "signed_date": self._extract_sales_signed_date(raw),
                    "document_number": detailed.get("number"),
                    "organization": detailed.get("organization"),
                    "operation_type": raw.get("ВидОперации"),
                    "operation_type_display": self._format_sales_operation_type(raw),
                    "amount": detailed.get("amount"),
                    "currency": detailed.get("currency"),
                    "counterparty": detailed.get("counterparty"),
                    "warehouse": self._extract_sales_warehouse(raw),
                    "issue_method": raw.get("СпособВыпискиАктовВыполненныхРабот"),
                    "issue_method_display": self._format_enum_label(raw.get("СпособВыпискиАктовВыполненныхРабот")),
                    "responsible": self._resolve_reference_value("Ответственный_Key", raw.get("Ответственный_Key")),
                    "comment": raw.get("Комментарий"),
                    "status": self._extract_document_status(raw, self._map_document_fields(list(raw.keys()))),
                    "source_entity": entity_name,
                }
            )

        rows.sort(
            key=lambda item: (
                self._parse_datetime_like(item.get("date")) or datetime.min,
                str(item.get("document_number") or ""),
            ),
            reverse=True,
        )
        return {
            "count_returned": len(rows[:effective_limit]),
            "data": rows[:effective_limit],
            "filters_applied_in_python": {
                "date_from": validated_from,
                "date_to": validated_to,
                "counterparty_name": counterparty_name,
                "limit": effective_limit,
            },
            "source": source,
            "warnings": warnings,
            "note": "Read-only sales journal view from published OData. Приближен к журналу 'Реализации ТМЗ и услуг' в 1С.",
        }

    def _get_recent_sales_documents(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        counterparty_name: str | None = None,
        max_documents: int = 200,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        source = self.discover_sales_sources(limit=1, check_data=True)
        if not source:
            return {
                "source": None,
                "count_returned": 0,
                "data": [],
                "warnings": ["Не найден безопасный источник реализаций в OData."],
        }
        candidate = source[0]
        entity_name = str(candidate.get("entity") or "Document_РеализацияТоваровУслуг")
        mapped = candidate.get("mapped_fields") or {}
        headers = self._get_recent_sales_headers(
            entity_name=entity_name,
            mapped=mapped,
            date_from=date_from,
            date_to=date_to,
            counterparty_name=counterparty_name,
            max_documents=max_documents,
            warnings=warnings,
        )
        deduped: list[dict[str, Any]] = []
        for header in headers:
            ref_key = str(header.get("reference") or "")
            raw = self._fetch_raw_entity_by_ref(entity_name, ref_key)
            if not raw:
                continue
            normalized = self._normalize_sales_row(raw, mapped)
            deduped.append(normalized)
        if not deduped:
            warnings.append("В текущей OData-публикации не найдено строк по реализациям для заданных фильтров.")
        return {
            "source": candidate,
            "count_returned": len(deduped),
            "data": deduped,
            "warnings": warnings,
        }

    def _get_recent_sales_headers(
        self,
        *,
        entity_name: str,
        mapped: dict[str, Any],
        date_from: str | None,
        date_to: str | None,
        counterparty_name: str | None,
        max_documents: int,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        page_size = min(max(max_documents, 50), 100)
        validated_from = self._parse_date_like(date_from) if date_from else None
        validated_to = self._parse_date_like(date_to) if date_to else None
        header_select = self._build_sales_header_select(entity_name, mapped)
        raw_rows = self._read_recent_tail_rows(
            entity_name,
            select=header_select,
            page_size=page_size,
            tail_pages=max(4, min(10, (max_documents // 10) + 4)),
            max_probe_skip=min(self.settings.max_top * 100, 50000),
            warnings=warnings,
        )
        rows: list[dict[str, Any]] = []
        document_mapped = self._map_document_fields(list({*header_select, "Posted", "DeletionMark"}))
        if mapped.get("counterparty"):
            document_mapped["counterparty"] = mapped.get("counterparty")
        if mapped.get("amount"):
            document_mapped["amount"] = mapped.get("amount")
        if mapped.get("date"):
            document_mapped["date"] = mapped.get("date")
        if mapped.get("number"):
            document_mapped["number"] = mapped.get("number")
        document_mapped["reference"] = "Ref_Key"
        for raw in raw_rows:
            row = self._normalize_document_search_row(raw, entity_name, document_mapped)
            row_date = self._parse_date_like(row.get("date"))
            if validated_to and row_date and row_date > validated_to:
                continue
            if validated_from and row_date and row_date < validated_from:
                continue
            if counterparty_name and not self._text_match(row.get("counterparty"), counterparty_name):
                continue
            rows.append(row)
        rows.sort(
            key=lambda item: (
                self._parse_datetime_like(item.get("date")) or datetime.min,
                str(item.get("number") or ""),
            ),
            reverse=True,
        )
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for row in rows:
            key = (row.get("number"), row.get("date"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= max_documents:
                break
        return deduped

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
            candidate_matches = 0
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
            try:
                candidate_rows, _tail_used = self._load_document_source_rows(
                    candidate["entity"],
                    select=select or None,
                    filter_expr=filter_expr or None,
                    orderby=f"{mapped['date']} desc" if mapped.get("date") else None,
                    limit=min(max(effective_limit * 3, 20), 80, self.settings.max_top),
                    page_size=min(max(effective_limit * 2, 20), 60, self.settings.max_top),
                    tail_pages=3,
                    max_probe_skip=min(self.settings.max_top * 100, 50000),
                    warnings=warnings,
                    prefer_recent_tail=True,
                )
            except ODataError as exc:
                if self._is_access_denied_error(exc):
                    warnings.append(
                        f"Источник {candidate['entity']} пропущен: bounded fallback read is not accessible for this entity in current 1C publication."
                    )
                    continue
                raise
            for row in candidate_rows or []:
                normalized = self._normalize_document_search_row(row, candidate["entity"], mapped)
                if not self._text_match(normalized.get("number"), needle):
                    continue
                if (validated_from or validated_to) and not self._date_in_range(normalized.get("date"), validated_from, validated_to):
                    continue
                rows.append(normalized)
                candidate_matches += 1
            if document_type and candidate_matches > 0:
                break
            if len(rows) >= effective_limit and (document_type or checked_candidates >= 3):
                warnings.append("Поиск остановлен после достижения лимита в наиболее релевантных document-like источниках.")
                break

        deduped_rows: list[dict[str, Any]] = []
        seen_document_rows: set[tuple[str, str, str, str]] = set()
        for row in rows:
            row_key = (
                str(row.get("document_type") or ""),
                str(row.get("reference") or ""),
                str(row.get("number") or ""),
                str(row.get("date") or ""),
            )
            if row_key in seen_document_rows:
                continue
            seen_document_rows.add(row_key)
            deduped_rows.append(row)
        rows = deduped_rows

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
            purchase_receipt_source = self._select_primary_purchase_receipt_source(limit=5)
            purchases = self.get_purchase_documents(
                date_from=validated_from,
                date_to=validated_to,
                counterparty=counterparty_name,
                limit=fetch_limit,
                entity_name=(purchase_receipt_source or {}).get("entity"),
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
        normalized: list[dict[str, Any]] = []
        source = source_candidates[0]
        source_entities_used: list[str] = []
        first_source_with_rows: dict[str, Any] | None = None
        page_size = min(max(limit * 20, 250), self.settings.max_top)

        for idx, candidate in enumerate(source_candidates[:6]):
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
            orderby = f"{mapped['date']} desc" if mapped.get("date") else None
            try:
                rows, filter_fallback_used = self._load_document_source_rows(
                    candidate["entity"],
                    select=select,
                    filter_expr=filter_expr,
                    orderby=orderby,
                    limit=limit,
                    page_size=page_size,
                    tail_pages=max(2, min(6, (limit // 5) + 2)),
                    max_probe_skip=min(self.settings.max_top * 100, 50000),
                    warnings=warnings,
                    prefer_recent_tail=not bool(effective_from or effective_to or counterparty),
                )
            except ODataError:
                if entity_name:
                    raise
                warnings.append(f"Источник {candidate['entity']} пропущен: безопасное чтение не удалось.")
                continue

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

            if candidate_normalized:
                source_entities_used.append(str(candidate.get("entity")))
                normalized.extend(candidate_normalized[: min(max(limit * 5, 50), self.settings.max_top)])
                if first_source_with_rows is None:
                    first_source_with_rows = candidate
                source = candidate
                if entity_name:
                    break
            elif idx < len(source_candidates) - 1:
                warnings.append(f"Источник {candidate['entity']} не вернул строк по текущим фильтрам. Пробуем следующий safe candidate.")

        normalized.sort(
            key=lambda r: (
                self._parse_datetime_like(r.get("date")) or datetime.min,
                self._to_decimal(r.get("amount"), default=Decimal("0")) or Decimal("0"),
            ),
            reverse=True,
        )
        deduped: list[dict[str, Any]] = []
        seen_keys: set[tuple[Any, Any, Any]] = set()
        for row in normalized:
            dedupe_key = (row.get("reference"), row.get("number"), row.get("date"))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            deduped.append(row)
        normalized = deduped

        if first_source_with_rows is not None:
            source = first_source_with_rows
        mapped = source.get("mapped_fields") or {}
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
            "source_entities_used": source_entities_used,
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

        endpoint_health: dict[str, Any] | None = None
        if url_ok:
            try:
                endpoint_health = self.check_endpoint_health(check_metadata=False)
                checks.append(
                    {
                        "name": "endpoint connectivity",
                        "status": "ok" if endpoint_health["server_alive"] else "error",
                        "details": {
                            "host": endpoint_health["host"],
                            "port": endpoint_health["port"],
                            "host_resolvable": endpoint_health["host_resolvable"],
                            "tcp_reachable": endpoint_health["tcp_reachable"],
                        },
                    }
                )
                if not endpoint_health["server_alive"]:
                    recommendations.append("Сервер 1С/OData недоступен по сети. Проверьте, жив ли host, открыт ли порт публикации и доступен ли веб-сервер 1С.")
            except Exception as exc:
                checks.append({"name": "endpoint connectivity", "status": "error", "details": str(exc)[:300]})
                recommendations.append("Не удалось выполнить быструю сетевую проверку OData endpoint. Проверьте адрес и сетевую доступность сервера 1С.")

        metadata_ok = False
        entities: list[EntityInfo] = []
        if endpoint_health is not None and not endpoint_health["server_alive"]:
            checks.append({"name": "$metadata readable", "status": "error", "details": "skipped because endpoint connectivity check failed"})
            recommendations.append("Проверьте URL публикации OData, логин/пароль, права пользователя, доступность хоста и порта публикации 1С.")
        else:
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
            "endpoint_health": endpoint_health,
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
            "исходяще",
            "оплатапоставщику",
            "перечисление",
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
            "оплатаотпокупателяплатежнойкартой",
            "отчеторозничныхпродажахоплата",
            "чекккмоплата",
            "входяще",
            "оплатапокупателя",
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

        if any(term in haystack for term in ["списаниесбанковскогосчета", "списаниесрасчетногосчета", "поступлениенабанковскийсчет", "поступлениенарасчетныйсчет", "платежноепоручениеисходящее", "платежноепоручениевходящее", "платежныйордерпоступлениеденежныхсредств", "платежныйордерсписаниеденежныхсредств", "оплатаотпокупателяплатежнойкартой"]):
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
            "currency": ["валютадокументаkey", "валютаkey", "валюта", "currency"],
        }
        mapped = self._map_fields_by_patterns(field_names, patterns)
        if "Контрагент_Key" in field_names:
            mapped["counterparty"] = "Контрагент_Key"
        elif "Контрагент" in field_names:
            mapped["counterparty"] = "Контрагент"
        return mapped

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
        for key in ("counterparty", "amount", "date", "number", "organization", "currency"):
            value = mapped.get(key)
            if value and value not in out:
                out.append(value)
        return out

    def _build_sales_header_select(self, entity_name: str, mapped: dict[str, str | None]) -> list[str]:
        entity = self.describe_entity(entity_name)
        field_names = {field.name for field in (entity.fields or [])} if entity else set()
        preferred = [
            "Ref_Key",
            mapped.get("number"),
            mapped.get("date"),
            mapped.get("counterparty"),
            mapped.get("amount"),
            mapped.get("organization"),
            mapped.get("currency"),
            "Склад_Key",
            "ВидОперации",
            "ДатаПодписанияГЗ",
            "ДатаПодписанияАкта",
            "СпособВыпискиАктовВыполненныхРабот",
            "СчетНаОплатуПокупателю_Key",
            "ДокументРасчетовСКонтрагентом",
            "ДокументРасчетовСКонтрагентом_Type",
            "Ответственный_Key",
            "Комментарий",
            "Posted",
            "DeletionMark",
        ]
        out: list[str] = []
        for field in preferred:
            if field and field in field_names and field not in out:
                out.append(field)
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
        try:
            response = self._get(path, params={"$select": ",".join(select_fields)}, headers={"Accept": "application/xml"})
        except ODataError:
            response = None
        out: dict[str, Any] | None = None
        if response is not None and response.status_code < 400:
            try:
                root = ET.fromstring(response.text)
            except ET.ParseError:
                root = None
            if root is not None:
                properties = None
                for node in root.iter():
                    if self._xml_local_name(node.tag) == "properties":
                        properties = node
                        break
                if properties is not None:
                    parsed: dict[str, Any] = {}
                    for child in properties:
                        local_name = self._xml_local_name(child.tag)
                        if local_name in select_fields:
                            parsed[local_name] = child.text
                    out = parsed or None
        if out is None:
            payload = self._query_entity_reference_fallback(entity_name, ref_key, select_fields)
            if payload:
                out = payload
        self._reference_cache[cache_key] = out
        return self._reference_cache[cache_key]

    def _query_entity_reference_fallback(
        self,
        entity_name: str,
        ref_key: str,
        select_fields: tuple[str, ...],
    ) -> dict[str, Any] | None:
        top = min(max(self.settings.max_top, 1), 1000)
        try:
            payload = self.query_entity(
                entity_name,
                top=top,
                select=["Ref_Key", *select_fields],
            )
        except ODataError:
            payload = None
        if payload:
            for row in payload.get("data") or []:
                if str(row.get("Ref_Key") or "") == ref_key:
                    return {field: row.get(field) for field in select_fields if row.get(field) not in (None, "")}
        merged: dict[str, Any] = {}
        for field in select_fields:
            try:
                payload = self.query_entity(entity_name, top=top, select=["Ref_Key", field])
            except ODataError:
                continue
            for row in payload.get("data") or []:
                if str(row.get("Ref_Key") or "") == ref_key and row.get(field) not in (None, ""):
                    merged[field] = row.get(field)
                    break
        return merged or None

    def _fetch_raw_entity_by_ref(self, entity_name: str, ref_key: str) -> dict[str, Any] | None:
        if not self._is_guid_like(ref_key) or ref_key == "00000000-0000-0000-0000-000000000000":
            return None
        self._validate_identifier(entity_name, "entity_name")
        path = f"{entity_name}(guid'{ref_key}')"
        try:
            response = self._get(path)
        except ODataError:
            try:
                payload = self.query_entity(entity_name, top=min(max(self.settings.max_top, 1), 1000))
            except ODataError:
                return None
            for row in payload.get("data") or []:
                if str(row.get("Ref_Key") or "") == ref_key:
                    return row
            return None
        if response.status_code >= 400:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _preferred_display_fields_for_entity(entity_name: str) -> tuple[str, ...]:
        if entity_name.startswith("Document_"):
            return ("Number", "Date")
        if entity_name.startswith("ChartOfAccounts_"):
            return ("Code", "Description")
        if entity_name in {"Catalog_Склады", "Catalog_Кассы", "Catalog_Организации"}:
            return ("Description", "Code")
        if entity_name in {"Catalog_Пользователи", "Catalog_ПодразделенияОрганизаций", "Catalog_ДоговорыКонтрагентов", "Catalog_Доходы", "Catalog_СтатьиЗатрат", "Catalog_НоменклатурныеГруппы"}:
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
        if "ответствен" in normalized or "автор" in normalized or "пользоват" in normalized:
            return "Catalog_Пользователи"
        if "подраздел" in normalized:
            return "Catalog_ПодразделенияОрганизаций"
        if "счетнаоплатупокупателю" in normalized:
            return "Document_СчетНаОплатуПокупателю"
        if "договорконтрагента" in normalized:
            return "Catalog_ДоговорыКонтрагентов"
        if "счетбанк" in normalized or "банковскиесчет" in normalized:
            return "Catalog_БанковскиеСчета"
        if "организац" in normalized:
            return "Catalog_Организации"
        return None

    @staticmethod
    def _is_guid_like(value: Any) -> bool:
        return isinstance(value, str) and bool(_GUID_RE.fullmatch(value))

    @staticmethod
    def _is_zero_guid_value(value: Any) -> bool:
        return isinstance(value, str) and value == "00000000-0000-0000-0000-000000000000"

    def _discover_document_search_candidates(self, document_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        requested_type = self._norm(document_type).replace("-", "").replace(" ", "") if document_type else ""
        deduped: dict[str, dict[str, Any]] = {}
        for entity in self.list_entities():
            name = self._norm(entity.name).replace("-", "").replace(" ", "")
            etype = self._norm(entity.entity_type).replace("-", "").replace(" ", "")
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
            score += self._document_type_hint_score_boost(requested_type, name, etype)

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

    def _document_type_hint_score_boost(self, requested_type: str, name: str, etype: str) -> int:
        if not requested_type:
            return 0
        haystack = f"{name} {etype}"
        boost = 0
        if "счетфактура" in requested_type:
            if "счетфактураполученный" in haystack or "счетфактуравыданный" in haystack:
                boost += 80
        elif "платеж" in requested_type or "оплат" in requested_type:
            if any(term in haystack for term in ("платежноепоручение", "платежныйордер", "платежнойкартой", "кассовыйордер")):
                boost += 70
        elif "поступление" in requested_type:
            if any(term in haystack for term in ("поступлениетоваровуслуг", "поступлениедопрасходов", "поступлениеизпереработки", "поступлениенма")):
                boost += 160
            if any(term in haystack for term in ("поступлениенабанковскийсчет", "платежныйордерпоступлениеденежныхсредств", "приходныйкассовыйордер")):
                boost -= 120
        elif "реализац" in requested_type:
            if "реализациятоваровуслуг" in haystack:
                boost += 80
        return boost

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
        if any(term in haystack for term in ["банков", "bank", "расчетногосчета", "банковскогосчета", "платежноепоручение", "платежныйордер", "платежнойкартой", "эквайр"]):
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

    def _document_number_matches(self, actual: str, requested: str) -> bool:
        actual_clean = str(actual or "").strip()
        requested_clean = str(requested or "").strip()
        if not actual_clean or not requested_clean:
            return False
        if actual_clean == requested_clean:
            return True
        actual_digits = actual_clean.lstrip("0")
        requested_digits = requested_clean.lstrip("0")
        return bool(actual_digits) and actual_digits == requested_digits

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
        out: list[dict[str, Any]] = []
        for section_name in ("Товары", "Услуги"):
            rows = raw.get(section_name)
            if not isinstance(rows, list):
                continue
            for row in rows:
                name = (
                    row.get("Содержание")
                    or row.get("Description")
                    or self._resolve_reference_value("Номенклатура_Key", row.get("Номенклатура_Key"))
                    or self._resolve_reference_value("Номенклатура", row.get("Номенклатура"))
                )
                account_bu = self._resolve_account_field(row.get("СчетУчетаБУ_Key"))
                revenue_account_bu = self._resolve_account_field(row.get("СчетДоходовБУ_Key"))
                cogs_account_bu = self._resolve_account_field(row.get("СчетСписанияСебестоимостиБУ_Key"))
                account_bu_inferred = self._infer_account_label(str(row.get("СчетУчетаБУ_Key") or ""))
                revenue_account_bu_inferred = self._infer_account_label(str(row.get("СчетДоходовБУ_Key") or ""))
                cogs_account_bu_inferred = self._infer_account_label(str(row.get("СчетСписанияСебестоимостиБУ_Key") or ""))
                revenue_analytics_bu = self._extract_subkonto_values(
                    row,
                    "СубконтоДоходовБУ",
                    (
                        row.get("СубконтоДоходовБУ1"),
                        row.get("СубконтоДоходовБУ2"),
                        row.get("СубконтоДоходовБУ3"),
                    ),
                )
                cogs_analytics_bu = self._extract_subkonto_values(
                    row,
                    "СубконтоСписанияСебестоимостиБУ",
                    (
                        row.get("СубконтоСписанияСебестоимостиБУ1"),
                        row.get("СубконтоСписанияСебестоимостиБУ2"),
                        row.get("СубконтоСписанияСебестоимостиБУ3"),
                    ),
                )
                account_bu_display = self._best_account_display(account_bu, account_bu_inferred)
                revenue_account_bu_display = self._best_account_display(revenue_account_bu, revenue_account_bu_inferred)
                cogs_account_bu_display = self._best_account_display(cogs_account_bu, cogs_account_bu_inferred)
                revenue_analytics_summary = self._format_analytics_summary(revenue_analytics_bu)
                cogs_analytics_summary = self._format_analytics_summary(cogs_analytics_bu)
                out.append(
                    {
                        "section": "goods" if section_name == "Товары" else "services",
                        "section_display": "ТМЗ" if section_name == "Товары" else "Услуги",
                        "name": name,
                        "item_key": row.get("Номенклатура_Key"),
                        "quantity": row.get("Количество"),
                        "price": row.get("Цена"),
                        "amount": row.get("Сумма"),
                        "account_bu": account_bu,
                        "account_bu_inferred_label": account_bu_inferred,
                        "revenue_account_bu": revenue_account_bu,
                        "revenue_account_bu_inferred_label": revenue_account_bu_inferred,
                        "cogs_account_bu": cogs_account_bu,
                        "cogs_account_bu_inferred_label": cogs_account_bu_inferred,
                        "account_bu_display": account_bu_display,
                        "revenue_account_bu_display": revenue_account_bu_display,
                        "cogs_account_bu_display": cogs_account_bu_display,
                        "revenue_analytics_bu": revenue_analytics_bu,
                        "cogs_analytics_bu": cogs_analytics_bu,
                        "revenue_analytics_summary": revenue_analytics_summary,
                        "cogs_analytics_summary": cogs_analytics_summary,
                        "accounting_view": {
                            "account_bu": account_bu,
                            "account_bu_inferred_label": account_bu_inferred,
                            "revenue_account_bu": revenue_account_bu,
                            "revenue_account_bu_inferred_label": revenue_account_bu_inferred,
                            "cogs_account_bu": cogs_account_bu,
                            "cogs_account_bu_inferred_label": cogs_account_bu_inferred,
                            "account_bu_display": account_bu_display,
                            "revenue_account_bu_display": revenue_account_bu_display,
                            "cogs_account_bu_display": cogs_account_bu_display,
                            "revenue_analytics_bu": revenue_analytics_bu,
                            "cogs_analytics_bu": cogs_analytics_bu,
                            "revenue_analytics_summary": revenue_analytics_summary,
                            "cogs_analytics_summary": cogs_analytics_summary,
                        },
                    }
                )
        return out

    def _extract_purchase_line_items(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for section_name in ("Товары", "Услуги"):
            rows = raw.get(section_name)
            if not isinstance(rows, list):
                continue
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
                        "item_key": row.get("Номенклатура_Key"),
                        "quantity": row.get("Количество"),
                        "amount": row.get("Сумма"),
                    }
                )
        return out

    def _extract_sales_signed_date(self, raw: dict[str, Any]) -> str | None:
        return (
            raw.get("ДатаПодписанияАкта")
            or raw.get("ДатаПодписанияГЗ")
            or raw.get("ДатаПодписания")
        )

    def _extract_sales_warehouse(self, raw: dict[str, Any]) -> Any:
        return self._resolve_reference_value("Склад_Key", raw.get("Склад_Key"))

    def _extract_sales_structural_unit(self, raw: dict[str, Any], organization: Any = None) -> Any:
        structural_unit = self._resolve_reference_value("СтруктурноеПодразделение_Key", raw.get("СтруктурноеПодразделение_Key"))
        if self._is_zero_guid_value(structural_unit):
            return organization
        return structural_unit

    def _extract_sales_invoice_number(self, raw: dict[str, Any]) -> str | None:
        invoice_ref = raw.get("СчетНаОплатуПокупателю_Key")
        if self._is_guid_like(invoice_ref):
            resolved = self._fetch_entity_by_ref("Document_СчетНаОплатуПокупателю", str(invoice_ref), ("Number", "Date"))
            if resolved:
                number = resolved.get("Number")
                if number not in (None, ""):
                    return str(number)
        basis_ref = raw.get("ДокументОснование")
        basis_type = raw.get("ДокументОснование_Type")
        if self._is_guid_like(basis_ref) and basis_type == "StandardODATA.Document_СчетНаОплатуПокупателю":
            resolved = self._fetch_entity_by_ref("Document_СчетНаОплатуПокупателю", str(basis_ref), ("Number", "Date"))
            if resolved:
                number = resolved.get("Number")
                if number not in (None, ""):
                    return str(number)
        return None

    def _extract_sales_invoice_document(self, raw: dict[str, Any]) -> str | None:
        invoice_ref = raw.get("СчетНаОплатуПокупателю_Key")
        if self._is_guid_like(invoice_ref):
            return self._resolve_document_reference_display("Document_СчетНаОплатуПокупателю", str(invoice_ref))
        basis_ref = raw.get("ДокументОснование")
        basis_type = raw.get("ДокументОснование_Type")
        if self._is_guid_like(basis_ref) and basis_type == "StandardODATA.Document_СчетНаОплатуПокупателю":
            return self._resolve_document_reference_display("Document_СчетНаОплатуПокупателю", str(basis_ref))
        return None

    def _extract_sales_settlement_document(self, raw: dict[str, Any]) -> str | None:
        doc_ref = raw.get("ДокументРасчетовСКонтрагентом")
        doc_type = raw.get("ДокументРасчетовСКонтрагентом_Type")
        if self._is_guid_like(doc_ref) and isinstance(doc_type, str) and "." in doc_type:
            entity_name = doc_type.split(".")[-1]
            return self._resolve_document_reference_display(entity_name, str(doc_ref))
        return None

    def _extract_sales_basis_document(self, raw: dict[str, Any]) -> str | None:
        basis_ref = raw.get("ДокументОснование")
        basis_type = raw.get("ДокументОснование_Type")
        if self._is_guid_like(basis_ref) and isinstance(basis_type, str) and "." in basis_type:
            entity_name = basis_type.split(".")[-1]
            return self._resolve_document_reference_display(entity_name, str(basis_ref))
        return None

    @staticmethod
    def _best_account_display(account_value: Any, inferred_label: str | None) -> str | None:
        if account_value not in (None, ""):
            return str(account_value)
        return inferred_label

    @staticmethod
    def _format_analytics_summary(values: list[Any]) -> str | None:
        parts = [str(value).strip() for value in values if value not in (None, "") and str(value).strip()]
        if not parts:
            return None
        return " / ".join(parts)

    def _format_sales_operation_type(self, raw: dict[str, Any]) -> str | None:
        operation = raw.get("ВидОперации")
        if operation in (None, ""):
            return "Реализация (Товары, услуги)"
        if operation in ("ПродажаКомиссия", "РеализацияТоваровУслуг"):
            has_goods = isinstance(raw.get("Товары"), list) and len(raw.get("Товары") or []) > 0
            has_services = isinstance(raw.get("Услуги"), list) and len(raw.get("Услуги") or []) > 0
            if has_goods and has_services:
                return "Реализация (Товары, услуги)"
            if has_goods:
                return "Реализация (Товары)"
            if has_services:
                return "Реализация (Услуги)"
            return "Реализация (Товары, услуги)"
        return self._format_enum_label(operation)

    def _resolve_account_field(self, value: Any) -> str | None:
        if not value:
            return None
        if self._is_guid_like(value):
            display = self._resolve_account_reference(str(value))
            if display:
                return display
            return str(value)[:8]
        return str(value)

    def _resolve_account_reference(self, ref_key: str) -> str | None:
        for entity_name in (
            "ChartOfAccounts_Хозрасчетный",
            "ChartOfAccounts_Бухгалтерский",
            "ChartOfAccounts_РабочийПланСчетов",
            "ChartOfAccounts_СчетаБухгалтерскогоУчета",
            "ChartOfAccounts_ХозрасчетныеСчета",
        ):
            payload = self._fetch_entity_by_ref(entity_name, ref_key, ("Code", "Description"))
            if payload:
                code = payload.get("Code")
                description = payload.get("Description")
                if code and description:
                    return f"{code} {description}"
                if code:
                    return str(code)
                if description:
                    return str(description)
        return None

    def _infer_account_label(self, ref_key: str) -> str | None:
        if not self._is_guid_like(ref_key):
            return None
        if ref_key in self._account_label_cache:
            return self._account_label_cache[ref_key]
        try:
            payload = self.query_entity("Catalog_КорреспонденцииСчетов", top=500)
        except ODataError:
            self._account_label_cache[ref_key] = None
            return None
        sales_hits: list[dict[str, Any]] = []
        purchase_hits: list[dict[str, Any]] = []
        generic_hits: list[dict[str, Any]] = []
        for row in payload.get("data") or []:
            is_dt = row.get("СчетДт_Key") == ref_key
            is_kt = row.get("СчетКт_Key") == ref_key
            if not is_dt and not is_kt:
                continue
            doc_type = str(row.get("ТипДокумента") or "")
            op_type = str(row.get("ВидОперацииДокумента") or "")
            content = str(row.get("Содержание") or "")
            bucket_row = {
                "is_dt": is_dt,
                "is_kt": is_kt,
                "doc_type": doc_type,
                "op_type": op_type,
                "content": content,
            }
            doc_text = f"{doc_type} {op_type} {content}".lower()
            if "реализац" in doc_text:
                sales_hits.append(bucket_row)
            elif "поступлен" in doc_text or "приобретен" in doc_text or "товар" in doc_text:
                purchase_hits.append(bucket_row)
            else:
                generic_hits.append(bucket_row)
        inferred = self._infer_account_label_from_hits(sales_hits, purchase_hits, generic_hits)
        self._account_label_cache[ref_key] = inferred
        return inferred

    @staticmethod
    def _infer_account_label_from_hits(
        sales_hits: list[dict[str, Any]],
        purchase_hits: list[dict[str, Any]],
        generic_hits: list[dict[str, Any]],
    ) -> str | None:
        sales_text = " ".join(
            f"{row.get('doc_type','')} {row.get('op_type','')} {row.get('content','')}".lower()
            for row in sales_hits
        )
        purchase_text = " ".join(
            f"{row.get('doc_type','')} {row.get('op_type','')} {row.get('content','')}".lower()
            for row in purchase_hits
        )
        generic_text = " ".join(
            f"{row.get('doc_type','')} {row.get('op_type','')} {row.get('content','')}".lower()
            for row in generic_hits
        )
        if "договорную стоимость" in sales_text or "доход" in sales_text:
            return "Доход от реализации"
        if "себестоим" in sales_text:
            return "Себестоимость реализации"
        if "реализация товаров" in sales_text and any(row.get("is_dt") for row in sales_hits):
            return "Себестоимость реализации"
        if "реализация товаров" in sales_text and any(row.get("is_kt") for row in sales_hits):
            return "Товары"
        if "приобретение товаров" in purchase_text or "поступление товаров" in purchase_text:
            return "Товары"
        if "товар" in generic_text:
            return "Товары"
        return None

    def _extract_subkonto_values(self, row: dict[str, Any], prefix: str, values: tuple[Any, Any, Any]) -> list[str]:
        out: list[str] = []
        for idx, value in enumerate(values, start=1):
            if value in (None, "", "00000000-0000-0000-0000-000000000000"):
                continue
            resolved = self._resolve_typed_reference_display(value, row.get(f"{prefix}{idx}_Type")) or value
            text = str(resolved).strip()
            if text and text not in out:
                out.append(text)
        return out

    def _resolve_typed_reference_display(self, value: Any, type_name: Any) -> str | None:
        if not self._is_guid_like(value) or not isinstance(type_name, str) or "." not in type_name:
            return None
        entity_name = type_name.split(".")[-1]
        preferred_fields = self._preferred_display_fields_for_entity(entity_name)
        payload = self._fetch_entity_by_ref(entity_name, str(value), preferred_fields)
        if not payload:
            return None
        for field in preferred_fields:
            resolved = payload.get(field)
            if resolved not in (None, ""):
                return str(resolved)
        return None

    def _resolve_document_reference_display(self, entity_name: str, ref_key: str) -> str | None:
        payload = self._fetch_entity_by_ref(entity_name, ref_key, ("Number", "Date"))
        if not payload:
            return None
        number = payload.get("Number")
        doc_date = payload.get("Date")
        if number in (None, "") and doc_date in (None, ""):
            return None
        if number not in (None, "") and doc_date not in (None, ""):
            return f"{number} от {str(doc_date)[:10]}"
        if number not in (None, ""):
            return str(number)
        return str(doc_date)[:10]

    @staticmethod
    def _format_enum_label(value: Any) -> str | None:
        if value in (None, ""):
            return None
        raw = str(value).strip()
        known = {
            "ВБумажномВиде": "В бумажном виде",
            "ВЭлектронномВиде": "В электронном виде",
            "РеализацияТоваровУслуг": "Реализация товаров услуг",
            "ПродажаКомиссия": "Продажа комиссия",
        }
        if raw in known:
            return known[raw]
        text = raw.replace("_", " ").strip()
        text = re.sub(r"(?<=[а-яa-z0-9])(?=[А-ЯA-Z])", " ", text)
        if not text:
            return None
        return text[:1].upper() + text[1:]

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

    @staticmethod
    def _parse_datetime_like(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        candidates = [
            text,
            text.replace(" ", "T"),
            text[:19] if len(text) >= 19 else text,
        ]
        for candidate in candidates:
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                continue
        parsed_date = OneCODataClient._parse_date_like(text)
        if parsed_date is None:
            return None
        return datetime.combine(parsed_date, datetime.min.time())

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(" ", "")
        if not text:
            return None
        text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
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
