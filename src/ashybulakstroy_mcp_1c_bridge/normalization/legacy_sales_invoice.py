from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    value = _clean(value).lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value, flags=re.IGNORECASE).strip()
    return re.sub(r"\s+", " ", value)


def parse_sales_invoice_text(text: str) -> dict[str, Any]:
    """Very small deterministic parser for Russian free-text sales invoices.

    It intentionally does not write to 1C. It extracts draft fields only; refs are
    resolved later via OData/metadata and explicit user confirmation.
    """
    raw = _clean(text)
    result: dict[str, Any] = {"raw_text": raw, "counterparty": None, "warehouse": None, "items": []}

    # Counterparty: common forms: "Ромашке: цемент 20" / "для ТОО Ромашка"
    before_colon, sep, after_colon = raw.partition(":")
    product_text = after_colon if sep else raw
    cp_match = re.search(r"(?:для|контрагенту|покупателю|на)\s+([^:;\n]+?)(?:\s+(?:товар|цемент|кирпич|арматур|на сумму)|:|$)", before_colon if sep else raw, re.IGNORECASE)
    if sep and before_colon.strip():
        cp = re.sub(r"(?i)\b(создай|сделай|реализацию|документ|для|на)\b", " ", before_colon)
        result["counterparty"] = re.sub(r"\s+", " ", cp).strip(" .,-") or None
    elif cp_match:
        result["counterparty"] = cp_match.group(1).strip(" .,-")

    wh_match = re.search(r"(?:склад|со склада|на складе)\s+([^,.;\n]+)", raw, re.IGNORECASE)
    if wh_match:
        result["warehouse"] = wh_match.group(1).strip(" .,-")

    pattern = re.compile(
        r"(?P<name>[А-Яа-яA-Za-z0-9 _\-./]+?)\s+"
        r"(?P<qty>\d+(?:[,.]\d+)?)\s*"
        r"(?P<unit>[А-Яа-яA-Za-z.]*)?"
        r"(?:\s+по\s+(?P<price>\d+(?:[,.]\d+)?))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(product_text):
        name = match.group("name").strip(" ,.;:-")
        name = re.sub(r"(?i)\b(создай|сделай|реализацию|для|на|товар|товары)\b", " ", name).strip()
        if len(name) < 2:
            continue
        row: dict[str, Any] = {"name": name, "quantity": float(match.group("qty").replace(",", "."))}
        unit = (match.group("unit") or "").strip()
        if unit:
            row["unit"] = unit
        price = match.group("price")
        if price:
            row["price"] = float(price.replace(",", "."))
        result["items"].append(row)
    return result


def _row_name(row: dict[str, Any]) -> str:
    for key in ("Description", "Наименование", "name", "Name", "Presentation", "presentation"):
        if row.get(key):
            return str(row[key])
    return str(row.get("Ref_Key") or row.get("Ref") or row)


def _row_ref(row: dict[str, Any]) -> str | None:
    for key in ("Ref_Key", "Ref", "Ссылка", "id", "uuid"):
        if row.get(key):
            return str(row[key])
    return None


def _score_candidate(name: str, query: str) -> float:
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0.0
    score = SequenceMatcher(None, q, n).ratio()
    if q == n:
        score = max(score, 1.0)
    if q in n:
        score = max(score, 0.82)
    return round(score, 3)


def find_entity_candidates(odata: Any, kind: str, query: str, limit: int = 10) -> dict[str, Any]:
    """Find likely 1C entities/records for user text.

    Uses OData metadata first to find the catalog, then samples rows. This is safe
    read-only discovery and does not assume exact Kazakhstan config names.
    """
    query = _clean(query)
    if not query:
        return {"kind": kind, "query": query, "candidates": [], "warning": "empty query"}

    terms = {
        "counterparty": ["контраген", "покупател", "customer", "buyer"],
        "item": ["номенклат", "товар", "item", "product"],
        "warehouse": ["склад", "warehouse"],
    }.get(kind, [kind])

    meta_hits: list[dict[str, Any]] = []
    for term in terms:
        meta_hits.extend(odata.search_metadata(term, limit=20))
    seen: set[str] = set()
    catalogs = []
    for hit in sorted(meta_hits, key=lambda x: x.get("score", 0), reverse=True):
        entity = hit.get("entity")
        if entity and entity not in seen and str(entity).startswith("Catalog_"):
            seen.add(entity)
            catalogs.append(entity)

    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for entity in catalogs[:5]:
        try:
            data = odata.query_entity(entity, top=min(max(limit, 1), 50)).get("data") or []
            for row in data:
                if not isinstance(row, dict):
                    continue
                name = _row_name(row)
                score = _score_candidate(name, query)
                if score >= 0.2 or _norm(query) in _norm(name):
                    candidates.append({"entity": entity, "name": name, "ref": _row_ref(row), "score": score, "raw": row})
        except Exception as exc:  # keep discovery resilient
            errors.append(f"{entity}: {exc}")

    candidates = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)[:limit]
    return {"kind": kind, "query": query, "catalogs_checked": catalogs[:5], "candidates": candidates, "errors": errors[:5]}


def normalize_sales_invoice_draft(odata: Any, payload: dict[str, Any] | None = None, text: str | None = None, confidence: float = 0.78) -> dict[str, Any]:
    payload = payload or parse_sales_invoice_text(text or "")
    issues: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {
        "document_type": "РеализацияТоваровУслуг",
        "source": payload,
        "counterparty": None,
        "warehouse": None,
        "items": [],
    }

    cp = payload.get("counterparty") or payload.get("контрагент") or payload.get("customer")
    if cp:
        found = find_entity_candidates(odata, "counterparty", cp, limit=5)
        top = (found.get("candidates") or [None])[0]
        if top and top.get("score", 0) >= confidence:
            normalized["counterparty"] = {"name": top.get("name"), "ref": top.get("ref"), "entity": top.get("entity"), "score": top.get("score")}
        else:
            issues.append({"code": "counterparty_unresolved", "field": "counterparty", "query": cp, "candidates": found.get("candidates", [])})
    else:
        issues.append({"code": "missing_counterparty", "field": "counterparty"})

    wh = payload.get("warehouse") or payload.get("склад")
    if wh:
        found = find_entity_candidates(odata, "warehouse", wh, limit=5)
        top = (found.get("candidates") or [None])[0]
        if top and top.get("score", 0) >= confidence:
            normalized["warehouse"] = {"name": top.get("name"), "ref": top.get("ref"), "entity": top.get("entity"), "score": top.get("score")}
        else:
            issues.append({"code": "warehouse_unresolved", "field": "warehouse", "query": wh, "candidates": found.get("candidates", [])})

    items = payload.get("items") or payload.get("goods") or []
    if not items:
        issues.append({"code": "missing_items", "field": "items"})
    for idx, row in enumerate(items):
        name = row.get("name") or row.get("item") or row.get("номенклатура") if isinstance(row, dict) else None
        qty = row.get("quantity") if isinstance(row, dict) else None
        price = row.get("price") if isinstance(row, dict) else None
        out = {"source": row, "quantity": qty, "price": price}
        if name:
            found = find_entity_candidates(odata, "item", name, limit=5)
            top = (found.get("candidates") or [None])[0]
            if top and top.get("score", 0) >= confidence:
                out.update({"item_name": top.get("name"), "item_ref": top.get("ref"), "entity": top.get("entity"), "score": top.get("score")})
            else:
                issues.append({"code": "item_unresolved", "field": f"items[{idx}]", "query": name, "candidates": found.get("candidates", [])})
        else:
            issues.append({"code": "missing_item_name", "field": f"items[{idx}].name"})
        try:
            if qty is None or float(qty) <= 0:
                issues.append({"code": "invalid_quantity", "field": f"items[{idx}].quantity"})
        except Exception:
            issues.append({"code": "invalid_quantity", "field": f"items[{idx}].quantity"})
        normalized["items"].append(out)

    return {"ok": not issues, "normalized": normalized, "issues": issues}
