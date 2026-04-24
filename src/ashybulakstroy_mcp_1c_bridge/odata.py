from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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
                severity = "critical" if qty <= 0 else ("high" if qty <= threshold / Decimal("2") else "medium")
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
            "counterparty_keywords": self._rank_entities_by_terms(entities, ["контрагент", "counterparty", "partner", "поставщик", "покупател"], limit=15),
            "nomenclature_keywords": self._rank_entities_by_terms(entities, ["номенклатур", "товар", "product", "item", "material", "материал"], limit=15),
        }
        inventory_candidates = self.discover_inventory_sources(limit=10, check_data=check_inventory_data)
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
