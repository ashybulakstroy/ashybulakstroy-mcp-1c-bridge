from __future__ import annotations

from typing import Any

from .buh.rpc import BuhError
from .buh.client import BuhClient


class DocumentService:
    """Document operations. Reads can use OData; create/post uses RPC.

    Posting is treated as a high-risk operation and is protected by a
    validate-before-post flow.
    """

    SALES_DOCUMENT_TYPE = "РеализацияТоваровУслуг"
    PURCHASE_DOCUMENT_TYPE = "ПоступлениеТоваровУслуг"

    def __init__(self, client: BuhClient) -> None:
        self.client = client

    async def find_documents(self, document_name: str, top: int = 50, filter_query: str | None = None) -> Any:
        return await self.client.get_document(document_name=document_name, top=top, filter_query=filter_query)

    async def get_document_status(self, document_type: str, document_ref: str) -> Any:
        if self.client.rpc:
            return await self.client.call("documents.get_status", {"document_type": document_type, "document_ref": document_ref})
        raise BuhError("Document status requires RPC method documents.get_status unless you query OData directly with odata_get")

    def validate_sales_invoice_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise BuhError("Sales invoice payload must be an object/dict")

        items = payload.get("items") or payload.get("Товары") or payload.get("goods")
        if not isinstance(items, list) or not items:
            raise BuhError("Sales invoice payload must contain non-empty items/Товары/goods list")

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise BuhError(f"Sales invoice item #{index + 1} must be an object")
            qty = item.get("quantity", item.get("Количество"))
            if qty is None:
                raise BuhError(f"Sales invoice item #{index + 1} must contain quantity/Количество")
            try:
                if float(qty) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise BuhError(f"Sales invoice item #{index + 1} quantity must be greater than zero")

        return {"ok": True, "items_count": len(items)}

    async def validate_sales_invoice(self, payload: dict[str, Any], check_stock: bool = True) -> Any:
        local = self.validate_sales_invoice_payload(payload)
        if check_stock and self.client.rpc:
            return await self.client.call("documents.validate_sales_invoice", {"payload": payload, "local_validation": local})
        return local

    def _extract_document_ref(self, result: Any) -> str:
        if not isinstance(result, dict):
            raise BuhError("RPC create document response must be an object to extract document reference", data=result)
        document_ref = result.get("document_ref") or result.get("ref") or result.get("Ref_Key") or result.get("id")
        if not document_ref:
            raise BuhError("Document created, but RPC response does not contain document_ref/ref/Ref_Key/id for posting", data=result)
        return str(document_ref)

    async def create_sales_invoice(self, payload: dict[str, Any], post: bool = False, validate: bool = True) -> Any:
        validation = await self.validate_sales_invoice(payload, check_stock=post) if validate else {"skipped": True}
        result = await self.client.create_document(self.SALES_DOCUMENT_TYPE, payload)
        if post:
            document_ref = self._extract_document_ref(result)
            post_result = await self.client.post_document(document_ref)
            return {"validation": validation, "created": result, "posted": post_result}
        return {"validation": validation, "created": result}

    async def create_purchase_invoice(self, payload: dict[str, Any], post: bool = False, validate: bool = True) -> Any:
        if validate and not isinstance(payload, dict):
            raise BuhError("Purchase invoice payload must be an object/dict")
        result = await self.client.create_document(self.PURCHASE_DOCUMENT_TYPE, payload)
        if post:
            document_ref = self._extract_document_ref(result)
            post_result = await self.client.post_document(document_ref)
            return {"created": result, "posted": post_result}
        return result

    async def post_document_validated(self, document_ref: str, document_type: str | None = None) -> Any:
        if self.client.rpc:
            validation = await self.client.call("documents.validate_before_post", {"document_ref": document_ref, "document_type": document_type})
            posted = await self.client.post_document(document_ref)
            return {"validation": validation, "posted": posted}
        raise BuhError("Posting documents requires RPC endpoint")

    async def unpost_document(self, document_ref: str) -> Any:
        if not self.client.rpc:
            raise BuhError("Unposting documents requires RPC method documents.unpost")
        return await self.client.call("documents.unpost", {"document_ref": document_ref})
