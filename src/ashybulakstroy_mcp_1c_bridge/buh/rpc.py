from __future__ import annotations

import itertools
from typing import Any

import httpx


class BuhError(RuntimeError):
    """Normalized error returned by 1C or by the transport layer."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        return {"message": str(self), "code": self.code, "data": self.data}


class BuhRpcClient:
    """Small JSON-RPC client for a 1C HTTP service.

    Expected 1C endpoint contract:
      POST {base_url}
      {"jsonrpc":"2.0", "method":"...", "params":{...}, "id":1}

    Response can be JSON-RPC ({"result": ...}) or a plain JSON object.
    """

    _ids = itertools.count(1)

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 30,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password) if username and password else None
        self.timeout = timeout_seconds
        self.verify_ssl = verify_ssl

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": next(self._ids),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl, auth=self.auth) as client:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BuhError(f"1C HTTP error: {exc.response.status_code}", data=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise BuhError(f"1C transport error: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise BuhError("1C returned non-JSON response", data=response.text) from exc

        if isinstance(data, dict) and data.get("error") is not None:
            error = data["error"]
            if isinstance(error, dict):
                raise BuhError(error.get("message", "1C JSON-RPC error"), code=error.get("code"), data=error.get("data"))
            raise BuhError(str(error))

        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    async def ping(self) -> Any:
        return await self.call("ping", {})

    async def get_balance(self, account: str | None = None, date_from: str | None = None, date_to: str | None = None) -> Any:
        return await self.call("accounting.get_balance", {
            "account": account,
            "date_from": date_from,
            "date_to": date_to,
        })

    async def get_counterparties(self, search: str | None = None, limit: int = 20) -> Any:
        return await self.call("directory.counterparties.search", {"search": search, "limit": limit})

    async def create_document(self, document_type: str, payload: dict[str, Any]) -> Any:
        return await self.call("documents.create", {"document_type": document_type, "payload": payload})

    async def post_document(self, document_ref: str) -> Any:
        return await self.call("documents.post", {"document_ref": document_ref})

# Backward-compatible aliases.
OneCError = BuhError
OneCClient = BuhRpcClient
