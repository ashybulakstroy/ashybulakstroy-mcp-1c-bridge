from __future__ import annotations

from typing import Any, Literal

from .odata import BuhODataClient
from .rpc import BuhRpcClient, BuhError

ConnectionMode = Literal["auto", "odata", "rpc"]


class BuhClient:
    """Unified 1C client.

    Routing policy:
    - read/list/search methods prefer OData when odata_url exists;
    - business actions prefer RPC because OData cannot reliably execute 1C business logic;
    - force mode with mode='odata' or mode='rpc' where the tool supports it.
    """

    READ_METHODS = {"ping", "get_counterparties", "get_catalog", "get_document", "odata_get", "odata_list_entities"}
    WRITE_METHODS = {"create_document", "post_document", "call"}

    def __init__(self, rpc: BuhRpcClient | None = None, odata: BuhODataClient | None = None, default_mode: ConnectionMode = "auto") -> None:
        self.rpc = rpc
        self.odata = odata
        self.default_mode = default_mode

    def _mode(self, mode: ConnectionMode | None) -> ConnectionMode:
        return mode or self.default_mode or "auto"

    def _require_rpc(self) -> BuhRpcClient:
        if not self.rpc:
            raise BuhError("RPC endpoint is not configured. Set BUH_RPC_URL or buh.rpc_url.")
        return self.rpc

    def _require_odata(self) -> BuhODataClient:
        if not self.odata:
            raise BuhError("OData endpoint is not configured. Set BUH_ODATA_URL or buh.odata_url.")
        return self.odata

    async def ping(self, mode: ConnectionMode | None = None) -> Any:
        selected = self._mode(mode)
        if selected == "odata":
            return await self._require_odata().list_entities()
        if selected == "rpc":
            return await self._require_rpc().ping()
        if self.odata:
            return {"mode": "odata", "result": await self.odata.list_entities()}
        return {"mode": "rpc", "result": await self._require_rpc().ping()}

    async def get_counterparties(self, search: str | None = None, limit: int = 20, mode: ConnectionMode | None = None) -> Any:
        selected = self._mode(mode)
        if selected == "odata":
            return await self._require_odata().get_counterparties(search=search, limit=limit)
        if selected == "rpc":
            return await self._require_rpc().get_counterparties(search=search, limit=limit)
        if self.odata:
            return await self.odata.get_counterparties(search=search, limit=limit)
        return await self._require_rpc().get_counterparties(search=search, limit=limit)

    async def get_balance(self, account: str | None = None, date_from: str | None = None, date_to: str | None = None, mode: ConnectionMode | None = None) -> Any:
        # Balance is usually a report/business calculation, so RPC is safer by default.
        selected = self._mode(mode)
        if selected == "odata":
            raise BuhError("Balance via OData is not universal in 1C. Use RPC or create a dedicated OData register query method.")
        return await self._require_rpc().get_balance(account=account, date_from=date_from, date_to=date_to)

    async def create_document(self, document_type: str, payload: dict[str, Any], mode: ConnectionMode | None = None) -> Any:
        selected = self._mode(mode)
        if selected == "odata":
            raise BuhError("Creating business documents through OData is unsafe here. Use RPC to run validation and 1C business logic.")
        return await self._require_rpc().create_document(document_type=document_type, payload=payload)

    async def post_document(self, document_ref: str, mode: ConnectionMode | None = None) -> Any:
        selected = self._mode(mode)
        if selected == "odata":
            raise BuhError("Posting documents is 1C business logic and must be executed through RPC.")
        return await self._require_rpc().post_document(document_ref=document_ref)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return await self._require_rpc().call(method, params or {})

    async def odata_get(self, entity: str, params: dict[str, Any] | None = None) -> Any:
        return await self._require_odata().get(entity, params=params)

    async def get_catalog(self, catalog_name: str, top: int = 50, filter_query: str | None = None) -> Any:
        return await self._require_odata().get_catalog(catalog_name=catalog_name, top=top, filter_query=filter_query)

    async def get_document(self, document_name: str, top: int = 50, filter_query: str | None = None) -> Any:
        return await self._require_odata().get_document(document_name=document_name, top=top, filter_query=filter_query)


# Backward-compatible alias for older imports.
OneCUnifiedClient = BuhClient
