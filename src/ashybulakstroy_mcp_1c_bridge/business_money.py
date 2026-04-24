from __future__ import annotations

from typing import Any

from .buh.rpc import BuhError
from .buh.client import BuhClient


class MoneyService:
    """Cash, bank and debt read operations."""

    def __init__(self, client: BuhClient) -> None:
        self.client = client

    async def get_cash_balance(self, date: str | None = None, cashbox: str | None = None) -> Any:
        if not self.client.rpc:
            raise BuhError("Cash balance requires RPC method money.get_cash_balance")
        return await self.client.call("money.get_cash_balance", {"date": date, "cashbox": cashbox})

    async def get_bank_balance(self, date: str | None = None, bank_account: str | None = None) -> Any:
        if not self.client.rpc:
            raise BuhError("Bank balance requires RPC method money.get_bank_balance")
        return await self.client.call("money.get_bank_balance", {"date": date, "bank_account": bank_account})

    async def get_counterparty_debt(
        self,
        counterparty: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> Any:
        if not self.client.rpc:
            raise BuhError("Counterparty debt requires RPC method money.get_counterparty_debt")
        return await self.client.call(
            "money.get_counterparty_debt",
            {"counterparty": counterparty, "date_from": date_from, "date_to": date_to, "limit": limit},
        )

    async def get_unpaid_invoices(self, counterparty: str | None = None, date_to: str | None = None, limit: int = 100) -> Any:
        if not self.client.rpc:
            raise BuhError("Unpaid invoices require RPC method money.get_unpaid_invoices")
        return await self.client.call("money.get_unpaid_invoices", {"counterparty": counterparty, "date_to": date_to, "limit": limit})

    async def find_payments(
        self,
        counterparty: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        amount: float | None = None,
        limit: int = 50,
    ) -> Any:
        if not self.client.rpc:
            raise BuhError("Payment search requires RPC method money.find_payments")
        return await self.client.call(
            "money.find_payments",
            {"counterparty": counterparty, "date_from": date_from, "date_to": date_to, "amount": amount, "limit": limit},
        )
