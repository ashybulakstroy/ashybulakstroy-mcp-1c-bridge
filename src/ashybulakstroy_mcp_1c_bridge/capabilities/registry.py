from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal, Any

RiskLevel = Literal["read", "write", "posting"]
Transport = Literal["odata", "rpc", "auto"]


@dataclass(frozen=True)
class Capability:
    """A stable business capability exposed by the bridge.

    Capabilities are higher-level than raw MCP tools. They describe what the
    system can do and which transport/risk controls should be used.
    """

    name: str
    title: str
    description: str
    tool: str
    preferred_transport: Transport
    risk: RiskLevel
    requires_validation: bool = False
    requires_rpc: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CAPABILITIES: dict[str, Capability] = {
    "metadata.inspect": Capability(
        name="metadata.inspect",
        title="Inspect 1C metadata",
        description="Discover OData metadata, catalogs, documents and endpoint health before hardcoding business operations.",
        tool="buh_inspect",
        preferred_transport="auto",
        risk="read",
    ),
    "stock.read": Capability(
        name="stock.read",
        title="Read stock balances",
        description="Read warehouse balances and check stock availability.",
        tool="get_stock_balance",
        preferred_transport="auto",
        risk="read",
    ),
    "stock.validate_before_sale": Capability(
        name="stock.validate_before_sale",
        title="Validate stock before sale",
        description="Check that requested goods are available before creating or posting a sales document.",
        tool="validate_sales_invoice",
        preferred_transport="rpc",
        risk="read",
        requires_rpc=True,
    ),
    "money.read": Capability(
        name="money.read",
        title="Read cash, bank and debt data",
        description="Read cash/bank balances, counterparty debts, unpaid invoices and payments.",
        tool="get_counterparty_debt",
        preferred_transport="rpc",
        risk="read",
        requires_rpc=True,
    ),

    "input.normalize_sales_invoice": Capability(
        name="input.normalize_sales_invoice",
        title="Normalize sales invoice input",
        description="Resolve human input to exact 1C refs/GUIDs before creating sales invoice: counterparty, warehouse and items.",
        tool="normalize_sales_invoice",
        preferred_transport="auto",
        risk="read",
        requires_validation=True,
    ),
    "documents.create": Capability(
        name="documents.create",
        title="Create business documents",
        description="Create 1C business documents through the RPC service so 1C validation/business logic is preserved.",
        tool="create_sales_invoice",
        preferred_transport="rpc",
        risk="write",
        requires_validation=True,
        requires_rpc=True,
    ),
    "documents.post": Capability(
        name="documents.post",
        title="Post business documents",
        description="Post an existing 1C document only after validation.",
        tool="post_document",
        preferred_transport="rpc",
        risk="posting",
        requires_validation=True,
        requires_rpc=True,
    ),
}


def list_capabilities() -> list[dict[str, Any]]:
    return [cap.to_dict() for cap in CAPABILITIES.values()]


def get_capability(name: str) -> dict[str, Any]:
    capability = CAPABILITIES.get(name)
    if capability is None:
        raise KeyError(f"Unknown capability: {name}")
    return capability.to_dict()
