from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..buh.client import BuhClient


def _as_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _entity_names(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        value = payload.get("value", payload.get("d", []))
        if isinstance(value, dict):
            value = value.get("results", [])
        if isinstance(value, list):
            names: list[str] = []
            for item in value:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("Name") or item.get("url") or item.get("Url")
                    if isinstance(name, str):
                        names.append(name.split("/")[-1])
            return names
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, str)]
    return []


def register_resources(mcp: FastMCP, buh: BuhClient) -> None:
    """Register read-only MCP resources.

    Resources expose stable context to the model. Mutations remain tools.
    """

    @mcp.resource("buh://health")
    async def buh_health() -> str:
        return _as_json(await buh.ping(mode="auto"))

    @mcp.resource("buh://metadata")
    async def buh_metadata() -> str:
        if not buh.odata:
            return _as_json({"ok": False, "error": "OData endpoint is not configured"})
        return _as_json(await buh.odata.metadata())

    @mcp.resource("buh://entities")
    async def buh_entities() -> str:
        if not buh.odata:
            return _as_json({"ok": False, "error": "OData endpoint is not configured"})
        return _as_json(await buh.odata.list_entities())

    @mcp.resource("buh://catalogs")
    async def buh_catalogs() -> str:
        if not buh.odata:
            return _as_json({"ok": False, "error": "OData endpoint is not configured"})
        entities = _entity_names(await buh.odata.list_entities())
        names = [x for x in entities if x.startswith("Catalog_")]
        return _as_json({"catalogs": sorted(names)})

    @mcp.resource("buh://documents")
    async def buh_documents() -> str:
        if not buh.odata:
            return _as_json({"ok": False, "error": "OData endpoint is not configured"})
        entities = _entity_names(await buh.odata.list_entities())
        names = [x for x in entities if x.startswith("Document_")]
        return _as_json({"documents": sorted(names)})

    @mcp.resource("buh://capabilities")
    async def buh_capabilities() -> str:
        from ..capabilities import list_capabilities
        return _as_json({"capabilities": list_capabilities()})

    @mcp.resource("buh://normalization/sales-invoice-template")
    async def buh_normalization_sales_invoice_template() -> str:
        return _as_json({
            "counterparty": "ТОО Ромашка",
            "warehouse": "Основной склад",
            "items": [
                {"name": "Цемент", "quantity": 20, "unit": "мешок", "price": 2500}
            ],
            "note": "Перед create_sales_invoice_normalized сначала вызови normalize_sales_invoice и проверь issues."
        })
