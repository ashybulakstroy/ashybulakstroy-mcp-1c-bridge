from __future__ import annotations

from typing import Any

from .buh.rpc import BuhError
from .buh.client import BuhClient


def _contains_description_filter(search: str) -> str:
    safe = search.replace("'", "''")
    return f"substringof('{safe}', Description) eq true"


class WarehouseService:
    """Warehouse read operations for 1C Kazakhstan accounting scenarios."""

    def __init__(self, client: BuhClient) -> None:
        self.client = client

    async def get_warehouses(self, search: str | None = None, limit: int = 50) -> Any:
        filter_query = _contains_description_filter(search) if search else None
        return await self.client.get_catalog("Склады", top=limit, filter_query=filter_query)

    async def find_item(self, search: str, limit: int = 20) -> Any:
        return await self.client.get_catalog("Номенклатура", top=limit, filter_query=_contains_description_filter(search))

    async def get_stock_balance(
        self,
        item: str | None = None,
        warehouse: str | None = None,
        date: str | None = None,
        limit: int = 100,
        register_entity: str | None = None,
        filter_query: str | None = None,
    ) -> Any:
        """Get stock balance.

        Preferred production path is RPC method warehouse.get_stock_balance because register names
        differ between 1C configurations. For pure OData discovery, pass register_entity explicitly.
        """
        if register_entity:
            params: dict[str, Any] = {"$top": limit}
            if filter_query:
                params["$filter"] = filter_query
            return await self.client.odata_get(register_entity, params)

        if not self.client.rpc:
            raise BuhError(
                "Stock balance requires either RPC method warehouse.get_stock_balance or explicit OData register_entity. "
                "Run inspect to find accumulation registers in your 1C publication."
            )
        return await self.client.call(
            "warehouse.get_stock_balance",
            {"item": item, "warehouse": warehouse, "date": date, "limit": limit},
        )

    async def check_stock_before_sale(self, items: list[dict[str, Any]], warehouse: str | None = None, date: str | None = None) -> Any:
        if not self.client.rpc:
            raise BuhError("check_stock_before_sale requires RPC method warehouse.check_stock_before_sale")
        return await self.client.call("warehouse.check_stock_before_sale", {"items": items, "warehouse": warehouse, "date": date})
