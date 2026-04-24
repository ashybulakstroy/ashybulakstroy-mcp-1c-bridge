from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from .odata import BuhODataClient
from .rpc import BuhRpcClient, BuhError


class BuhInspector:
    """Checks configured 1C endpoints and discovers OData metadata."""

    def __init__(self, rpc: BuhRpcClient | None = None, odata: BuhODataClient | None = None) -> None:
        self.rpc = rpc
        self.odata = odata

    async def check_rpc(self) -> dict[str, Any]:
        if not self.rpc:
            return {"available": False, "configured": False, "error": "RPC endpoint is not configured"}
        try:
            result = await self.rpc.ping()
            return {"available": True, "configured": True, "result": result}
        except Exception as exc:
            return {"available": False, "configured": True, "error": str(exc)}

    async def fetch_metadata(self) -> str:
        if not self.odata:
            raise BuhError("OData endpoint is not configured")
        url = f"{self.odata.base_url}/$metadata"
        try:
            async with httpx.AsyncClient(timeout=self.odata.timeout, verify=self.odata.verify_ssl, auth=self.odata.auth) as client:
                response = await client.get(url, headers={"Accept": "application/xml,text/xml,*/*"})
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as exc:
            raise BuhError(f"1C OData metadata HTTP error: {exc.response.status_code}", data=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise BuhError(f"1C OData metadata transport error: {exc}") from exc

    @staticmethod
    def parse_metadata(xml_text: str) -> dict[str, list[str]]:
        documents: set[str] = set()
        catalogs: set[str] = set()
        registers: set[str] = set()
        entities: set[str] = set()

        try:
            root = ET.fromstring(xml_text)
            for element in root.iter():
                name = element.attrib.get("Name") or element.attrib.get("EntityType")
                if not name:
                    continue
                entities.add(name)
                if name.startswith("Document_"):
                    documents.add(name)
                elif name.startswith("Catalog_"):
                    catalogs.add(name)
                elif name.startswith(("AccumulationRegister_", "AccountingRegister_", "InformationRegister_")):
                    registers.add(name)
        except ET.ParseError:
            # Fallback for non-standard namespace or partially malformed XML.
            for name in re.findall(r'Name="([^"]+)"', xml_text):
                entities.add(name)
                if name.startswith("Document_"):
                    documents.add(name)
                elif name.startswith("Catalog_"):
                    catalogs.add(name)
                elif name.startswith(("AccumulationRegister_", "AccountingRegister_", "InformationRegister_")):
                    registers.add(name)

        return {
            "documents": sorted(documents),
            "catalogs": sorted(catalogs),
            "registers": sorted(registers),
            "entities": sorted(entities),
        }

    async def inspect(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "error",
            "odata": {"available": False, "configured": bool(self.odata)},
            "rpc": await self.check_rpc(),
        }

        if self.odata:
            try:
                service_root = await self.odata.list_entities()
                metadata = await self.fetch_metadata()
                parsed = self.parse_metadata(metadata)
                result["odata"] = {
                    "available": True,
                    "configured": True,
                    "service_root_sample": service_root,
                    "documents_count": len(parsed["documents"]),
                    "catalogs_count": len(parsed["catalogs"]),
                    "registers_count": len(parsed["registers"]),
                    "documents": parsed["documents"],
                    "catalogs": parsed["catalogs"],
                    "registers": parsed["registers"],
                }
            except Exception as exc:
                result["odata"] = {"available": False, "configured": True, "error": str(exc)}

        if result["odata"].get("available") or result["rpc"].get("available"):
            result["status"] = "ok"
        return result


# Backward-compatible alias for older imports.
OneCInspector = BuhInspector
