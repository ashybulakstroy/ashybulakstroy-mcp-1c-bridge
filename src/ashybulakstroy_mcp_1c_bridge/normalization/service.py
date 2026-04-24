from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from typing import Any, Literal

from ..buh.client import BuhClient
from ..buh.rpc import BuhError

EntityKind = Literal["counterparty", "item", "warehouse"]


@dataclass
class NormalizationIssue:
    code: str
    message: str
    field: str | None = None
    severity: Literal["error", "warning", "question"] = "error"
    candidates: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, [], {})}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    value = _text(value).lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value, flags=re.IGNORECASE).strip()
    return re.sub(r"\s+", " ", value)


def _extract_name(row: dict[str, Any]) -> str:
    for key in ("Description", "Наименование", "name", "Name", "presentation", "Presentation"):
        val = row.get(key)
        if val:
            return str(val)
    return str(row.get("Ref_Key") or row.get("id") or row)


def _extract_ref(row: dict[str, Any]) -> str | None:
    for key in ("Ref_Key", "Ref", "Ссылка", "id", "uuid"):
        val = row.get(key)
        if val:
            return str(val)
    return None


def _odata_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("value", payload.get("d", []))
        if isinstance(value, dict):
            value = value.get("results", [])
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _candidate(row: dict[str, Any], query: str) -> dict[str, Any]:
    name = _extract_name(row)
    ref = _extract_ref(row)
    q = _norm(query)
    n = _norm(name)
    score = 1.0 if q and q == n else SequenceMatcher(None, q, n).ratio()
    if q and q in n:
        score = max(score, 0.82)
    return {"ref": ref, "name": name, "score": round(score, 3), "raw": row}


def _best(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)[0]


class NormalizationService:
    """Normalize human/business input into 1C-ready references and payloads."""

    DEFAULT_CONFIDENCE = 0.78

    def __init__(self, client: BuhClient, confidence_threshold: float | None = None) -> None:
        self.client = client
        self.confidence_threshold = confidence_threshold or self.DEFAULT_CONFIDENCE

    async def _search_catalog(self, catalog_name: str, search: str, limit: int = 10) -> list[dict[str, Any]]:
        if not self.client.odata:
            raise BuhError("AI normalization requires OData catalog search. Configure buh.odata_url and run inspect.")
        safe = search.replace("'", "''")
        filter_query = f"substringof('{safe}', Description) eq true"
        data = await self.client.get_catalog(catalog_name, top=limit, filter_query=filter_query)
        candidates = [_candidate(x, search) for x in _odata_items(data)]
        return sorted(candidates, key=lambda x: x["score"], reverse=True)

    async def find_candidates(self, kind: EntityKind, search: str, limit: int = 10) -> dict[str, Any]:
        catalog = {"counterparty": "Контрагенты", "item": "Номенклатура", "warehouse": "Склады"}[kind]
        candidates = await self._search_catalog(catalog, search, limit=limit)
        return {"kind": kind, "query": search, "catalog": f"Catalog_{catalog}", "candidates": candidates}

    async def resolve_entity(self, kind: EntityKind, value: Any, required: bool = True, limit: int = 10) -> dict[str, Any]:
        if isinstance(value, dict):
            explicit_ref = value.get("ref") or value.get("Ref_Key") or value.get("id")
            explicit_name = value.get("name") or value.get("Description") or value.get("Наименование")
            if explicit_ref:
                return {"resolved": True, "kind": kind, "ref": str(explicit_ref), "name": explicit_name or str(explicit_ref), "source": "explicit_ref", "candidates": []}
            value = explicit_name

        query = _text(value)
        if not query:
            if required:
                return {"resolved": False, "kind": kind, "issue": NormalizationIssue("missing_value", f"Не указано значение для {kind}", kind).to_dict()}
            return {"resolved": True, "kind": kind, "ref": None, "name": None, "source": "empty_optional", "candidates": []}

        candidates = (await self.find_candidates(kind, query, limit=limit))["candidates"]
        top = _best(candidates)
        if top and top.get("score", 0) >= self.confidence_threshold:
            close = [c for c in candidates if c is not top and abs(top["score"] - c.get("score", 0)) < 0.05]
            if close:
                return {"resolved": False, "kind": kind, "query": query, "issue": NormalizationIssue("ambiguous_match", f"Найдено несколько похожих значений для {query}", kind, "question", [top, *close[:4]]).to_dict(), "candidates": candidates}
            return {"resolved": True, "kind": kind, "query": query, "ref": top.get("ref"), "name": top.get("name"), "score": top.get("score"), "source": "odata_search", "candidates": candidates[:5]}

        return {"resolved": False, "kind": kind, "query": query, "issue": NormalizationIssue("not_found", f"Не удалось однозначно найти {query} в 1С", kind, "question", candidates[:5]).to_dict(), "candidates": candidates}

    def parse_free_text_invoice(self, text: str) -> dict[str, Any]:
        cleaned = _text(text)
        result: dict[str, Any] = {"raw_text": cleaned, "items": []}
        before_colon, sep, after_colon = cleaned.partition(":")
        product_text = after_colon if sep else cleaned
        if sep:
            result["counterparty"] = before_colon.replace("создай", "").replace("реализацию", "").replace("для", "").replace("на", "").strip(" .,-")
        pattern = re.compile(r"(?P<name>[А-Яа-яA-Za-z0-9 _\-./]+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>[А-Яа-яA-Za-z.]*)?(?:\s+по\s+(?P<price>\d+(?:[.,]\d+)?))?", re.IGNORECASE)
        for match in pattern.finditer(product_text):
            name = match.group("name").strip(" ,.;")
            if not name or len(name) < 2:
                continue
            item: dict[str, Any] = {"name": name, "quantity": float(match.group("qty").replace(",", "."))}
            if match.group("unit"):
                item["unit"] = match.group("unit")
            if match.group("price"):
                item["price"] = float(match.group("price").replace(",", "."))
            result["items"].append(item)
        return result

    async def normalize_sales_invoice(self, payload: dict[str, Any] | None = None, text: str | None = None, check_stock: bool = True) -> dict[str, Any]:
        if payload is None:
            if not text:
                raise BuhError("Provide either structured payload or free-text command for normalization")
            payload = self.parse_free_text_invoice(text)
        if not isinstance(payload, dict):
            raise BuhError("Normalization payload must be an object/dict")

        issues: list[dict[str, Any]] = []
        normalized: dict[str, Any] = {"document_type": "РеализацияТоваровУслуг", "source": payload, "counterparty": None, "warehouse": None, "items": []}

        counterparty_value = payload.get("counterparty") or payload.get("контрагент") or payload.get("buyer") or payload.get("customer")
        counterparty = await self.resolve_entity("counterparty", counterparty_value, required=True)
        if counterparty.get("resolved"):
            normalized["counterparty"] = {"ref": counterparty.get("ref"), "name": counterparty.get("name")}
        else:
            issues.append(counterparty.get("issue") or {"code": "counterparty_unresolved"})

        warehouse_value = payload.get("warehouse") or payload.get("склад")
        if warehouse_value:
            warehouse = await self.resolve_entity("warehouse", warehouse_value, required=False)
            if warehouse.get("resolved"):
                normalized["warehouse"] = {"ref": warehouse.get("ref"), "name": warehouse.get("name")}
            else:
                issues.append(warehouse.get("issue") or {"code": "warehouse_unresolved"})

        items = payload.get("items") or payload.get("Товары") or payload.get("goods") or []
        if not isinstance(items, list) or not items:
            issues.append(NormalizationIssue("missing_items", "Не указаны строки товаров/услуг", "items").to_dict())
            items = []

        for idx, row in enumerate(items):
            if not isinstance(row, dict):
                issues.append(NormalizationIssue("invalid_item", f"Строка #{idx + 1} должна быть объектом", f"items[{idx}]").to_dict())
                continue
            name = row.get("item") or row.get("name") or row.get("номенклатура") or row.get("Номенклатура")
            resolved = await self.resolve_entity("item", name or row, required=True)
            qty = row.get("quantity", row.get("Количество"))
            price = row.get("price", row.get("Цена"))
            normalized_item = {"source": row, "quantity": qty, "price": price, "unit": row.get("unit") or row.get("ЕдиницаИзмерения")}
            if resolved.get("resolved"):
                normalized_item.update({"item_ref": resolved.get("ref"), "item_name": resolved.get("name")})
            else:
                issues.append(resolved.get("issue") or {"code": "item_unresolved", "field": f"items[{idx}]"})
            try:
                if qty is None or float(qty) <= 0:
                    issues.append(NormalizationIssue("invalid_quantity", f"Количество в строке #{idx + 1} должно быть больше нуля", f"items[{idx}].quantity").to_dict())
            except (TypeError, ValueError):
                issues.append(NormalizationIssue("invalid_quantity", f"Количество в строке #{idx + 1} должно быть числом", f"items[{idx}].quantity").to_dict())
            if price is not None:
                try:
                    if float(price) < 0:
                        issues.append(NormalizationIssue("invalid_price", f"Цена в строке #{idx + 1} не может быть отрицательной", f"items[{idx}].price").to_dict())
                except (TypeError, ValueError):
                    issues.append(NormalizationIssue("invalid_price", f"Цена в строке #{idx + 1} должна быть числом", f"items[{idx}].price").to_dict())
            normalized["items"].append(normalized_item)

        blocking = {"ambiguous_match", "not_found", "missing_value", "missing_items", "invalid_item", "invalid_quantity", "invalid_price"}
        can_create = not any(i.get("code") in blocking for i in issues)
        result: dict[str, Any] = {"ok": can_create, "normalized": normalized, "issues": issues}

        if can_create and check_stock and self.client.rpc:
            stock_items = [{"item_ref": x.get("item_ref"), "quantity": x.get("quantity")} for x in normalized["items"]]
            result["stock_check"] = await self.client.call("warehouse.check_stock_before_sale", {"items": stock_items, "warehouse": normalized.get("warehouse")})

        return result

    async def create_sales_invoice_from_normalized(self, normalized_result: dict[str, Any], post: bool = False) -> dict[str, Any]:
        if not normalized_result.get("ok"):
            raise BuhError("Cannot create sales invoice: normalization has unresolved issues", data=normalized_result.get("issues"))
        payload = normalized_result["normalized"]
        rpc_payload = {
            "counterparty_ref": payload["counterparty"]["ref"],
            "warehouse_ref": (payload.get("warehouse") or {}).get("ref"),
            "items": [{"item_ref": item.get("item_ref"), "quantity": item.get("quantity"), "price": item.get("price"), "unit": item.get("unit")} for item in payload.get("items", [])],
            "source_normalized": payload,
        }
        created = await self.client.create_document("РеализацияТоваровУслуг", rpc_payload)
        result: dict[str, Any] = {"created": created, "payload": rpc_payload}
        if post:
            doc_ref = created.get("document_ref") or created.get("ref") or created.get("Ref_Key") or created.get("id") if isinstance(created, dict) else None
            if not doc_ref:
                raise BuhError("Document created, but response does not contain document reference for posting", data=created)
            result["posted"] = await self.client.post_document(str(doc_ref))
        return result
