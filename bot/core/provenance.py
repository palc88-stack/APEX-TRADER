"""Explicit provenance contracts for exchange-derived trading facts.

No value from this module should be treated as an exchange fill unless the
adapter has evidence from the exchange response itself.  Market data and
configured values are intentionally distinct from execution facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class FieldSource(str, Enum):
    EXCHANGE_FILL = "exchange_fill"
    EXCHANGE_MARKET_DATA = "exchange_market_data"
    CONFIGURED = "configured"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class FillDetails:
    """Independent provenance for every value used in execution accounting."""

    price: float
    price_source: FieldSource
    quantity: float
    quantity_source: FieldSource
    fee: float
    fee_source: FieldSource
    order_id: str = ""
    trade_ids: tuple[str, ...] = ()

    @property
    def is_pnl_eligible(self) -> bool:
        """PnL requires confirmed execution price, quantity and fee."""
        return (
            self.price > 0
            and self.quantity > 0
            and self.price_source is FieldSource.EXCHANGE_FILL
            and self.quantity_source is FieldSource.EXCHANGE_FILL
            and self.fee_source is FieldSource.EXCHANGE_FILL
        )

    @property
    def is_fee_confirmed(self) -> bool:
        return self.fee_source is FieldSource.EXCHANGE_FILL

    def as_record(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "price_source": self.price_source.value,
            "quantity": self.quantity,
            "quantity_source": self.quantity_source.value,
            "fee": self.fee,
            "fee_source": self.fee_source.value,
            "order_id": self.order_id,
            "trade_ids": list(self.trade_ids),
        }


class QueryOutcome(str, Enum):
    SUCCESS_WITH_DATA = "success_with_data"
    SUCCESS_EMPTY = "success_empty"
    FAILED = "failed"


@dataclass(frozen=True)
class QueryResult:
    outcome: QueryOutcome
    data: list[Any]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is not QueryOutcome.FAILED

    @classmethod
    def from_items(cls, items: Iterable[Any]) -> "QueryResult":
        data = list(items)
        outcome = (
            QueryOutcome.SUCCESS_WITH_DATA
            if data
            else QueryOutcome.SUCCESS_EMPTY
        )
        return cls(outcome=outcome, data=data)

    @classmethod
    def failed(cls, error: Exception | str) -> "QueryResult":
        return cls(QueryOutcome.FAILED, [], str(error))
