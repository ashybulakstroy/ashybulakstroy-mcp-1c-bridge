from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .rpc import BuhError


class BuhODataClient:
    """Async OData client for standard 1C publication.

    Typical base URL:
      http://server/base/odata/standard.odata
    """

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

    async def request(self, method: str, path: str, params: dict[str, Any] | None = None, json_body: Any = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl, auth=self.auth) as client:
                response = await client.request(method.upper(), url, params=params or {}, json=json_body, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BuhError(f"1C OData HTTP error: {exc.response.status_code}", data=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise BuhError(f"1C OData transport error: {exc}") from exc

        if not response.text.strip():
            return None
        try:
            data = response.json()
        except ValueError as exc:
            raise BuhError("1C OData returned non-JSON response", data=response.text) from exc

        if isinstance(data, dict) and "odata.error" in data:
            error = data["odata.error"]
            message = error.get("message", {}).get("value") if isinstance(error, dict) else str(error)
            raise BuhError(message or "1C OData error", data=error)

        return data

    async def get(self, entity: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", entity, params=params)

    async def list_entities(self) -> Any:
        return await self.get("")

    async def metadata(self) -> Any:
        # Return raw XML metadata. OData metadata is not JSON.
        url = f"{self.base_url}/$metadata"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl, auth=self.auth) as client:
                response = await client.get(url, headers={"Accept": "application/xml"})
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BuhError(f"1C OData metadata HTTP error: {exc.response.status_code}", data=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise BuhError(f"1C OData metadata transport error: {exc}") from exc
        return response.text

    async def get_counterparties(self, search: str | None = None, limit: int = 20) -> Any:
        params: dict[str, Any] = {"$top": limit}
        if search:
            safe = search.replace("'", "''")
            params["$filter"] = f"substringof('{safe}', Description) eq true"
        return await self.get("Catalog_Контрагенты", params=params)

    async def get_catalog(self, catalog_name: str, top: int = 50, filter_query: str | None = None) -> Any:
        params: dict[str, Any] = {"$top": top}
        if filter_query:
            params["$filter"] = filter_query
        return await self.get(f"Catalog_{catalog_name}", params=params)

    async def get_document(self, document_name: str, top: int = 50, filter_query: str | None = None) -> Any:
        params: dict[str, Any] = {"$top": top}
        if filter_query:
            params["$filter"] = filter_query
        return await self.get(f"Document_{document_name}", params=params)

    async def get_by_ref_key(self, entity: str, ref_key: str) -> Any:
        quoted = quote(ref_key, safe="")
        return await self.get(f"{entity}(guid'{quoted}')")

# Backward-compatible alias.
OneCODataClient = BuhODataClient
