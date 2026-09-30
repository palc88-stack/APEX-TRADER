"""Safely reconcile a manually closed Binance testnet trade.

This script is fail-closed: it changes no state unless Binance confirms that the
position quantity is zero. It never invents exit fills or realized PnL.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import ccxt
import requests


TRADE_ID = os.environ.get("RECONCILE_TRADE_ID", "317021174")
SYMBOL = os.environ.get("RECONCILE_SYMBOL", "RDNT/USDT:USDT")
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_WRITE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def sb(method: str, path: str, body: Any = None, prefer: str = "return=representation") -> Any:
    response = requests.request(
        method,
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
        json=body,
        timeout=20,
    )
    response.raise_for_status()
    return response.json() if response.text else None


def main() -> None:
    exchange = ccxt.binanceusdm({
        "apiKey": os.environ["BINANCE_API_KEY"],
        "secret": os.environ["BINANCE_SECRET_KEY"],
        "enableRateLimit": True,
        "options": {"defaultType": "future", "adjustForTimeDifference": True},
    })
    exchange.set_sandbox_mode(True)
    try:
        exchange.load_markets()
        order = exchange.fetch_order(TRADE_ID, SYMBOL)
        positions = exchange.fetch_positions([SYMBOL])
        position = next((p for p in positions if p.get("symbol") == SYMBOL), None)
        market_id = exchange.market(SYMBOL)["id"]
        try:
            algo_orders = exchange.request(
                "openAlgoOrders", "fapiPrivate", "GET", {"symbol": market_id}
            ) or []
        except Exception as exc:
            algo_orders = []
            print(json.dumps({"protection_query_error": str(exc)}))
        contracts = float((position or {}).get("contracts") or 0)
        position_side = (position or {}).get("side")
        order_status = order.get("status")
        filled = float(order.get("filled") or 0)
        average = order.get("average")
        observation = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "symbol": SYMBOL,
            "order_id": TRADE_ID,
            "order_status": order_status,
            "order_filled": filled,
            "order_average": average,
            "position_contracts": contracts,
            "position_side": position_side,
            "open_algo_orders": [
                {
                    "algoId": item.get("algoId"),
                    "type": item.get("orderType") or item.get("type"),
                    "triggerPrice": item.get("triggerPrice") or item.get("stopPrice"),
                    "quantity": item.get("quantity"),
                    "side": item.get("side"),
                }
                for item in algo_orders
            ],
        }
        print(json.dumps({"exchange_observation": observation}, default=str))

        rows = sb(
            "GET",
            f"trades?select=id,status,symbol&status=eq.NEEDS_RECONCILIATION&id=eq.{TRADE_ID}&limit=1",
        )
        if not rows:
            print("No NEEDS_RECONCILIATION record found; no state changed.")
            return

        if abs(contracts) > 1e-12:
            if filled <= 0 or not average or abs(contracts - filled) > max(1e-8, filled * 0.001):
                raise RuntimeError(
                    f"FAIL CLOSED: Binance position cannot be matched to entry fill: "
                    f"contracts={contracts}, filled={filled}, average={average}"
                )
            direction = "LONG" if contracts > 0 else "SHORT"
            note = (
                "Reconciled from Binance Testnet: an open position was confirmed. "
                f"Order status={order_status}, filled={filled}, average={average}, side={position_side}. "
                "No exit fill or realized PnL was inferred."
            )
            updated = sb(
                "PATCH",
                f"trades?id=eq.{TRADE_ID}&status=eq.NEEDS_RECONCILIATION",
                {
                    "status": "OPEN",
                    "direction": direction,
                    "entry_price": float(average),
                    "entry_quantity": filled,
                    "remaining_quantity": abs(contracts),
                    "entry_price_source": "exchange_fill",
                    "entry_quantity_source": "exchange_fill",
                    "reconciliation_note": note,
                },
            )
            released = False
        else:
            note = (
                "Manual reconciliation confirmed by Binance Testnet: current position quantity is zero. "
                f"Order status={order_status}, order filled={filled}, average={average}. "
                "No exit fill or realized PnL was inferred; accounting remains unconfirmed."
            )
            updated = sb(
                "PATCH",
                f"trades?id=eq.{TRADE_ID}&status=eq.NEEDS_RECONCILIATION",
                {
                    "status": "CLOSED",
                    "remaining_quantity": 0,
                    "close_reason": "manual",
                    "pnl_source": "unconfirmed_manual_reconciliation",
                    "exit_price_source": "unconfirmed",
                    "exit_quantity_source": "exchange_position_zero",
                    "exit_fee_source": "unconfirmed",
                    "reconciliation_note": note,
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            released = sb(
                "POST",
                "rpc/release_position_slot",
                {"p_symbol": SYMBOL, "p_trade_id": TRADE_ID, "p_reservation_id": None},
                prefer="return=minimal",
            )
        sb(
            "POST",
            "trading_events",
            {
                "event_type": "TRADE_RECONCILED",
                "idempotency_key": f"manual_reconcile:{TRADE_ID}:position-zero",
                "source": "github_manual_reconciliation",
                "trade_id": TRADE_ID,
                "symbol": SYMBOL,
                "payload": {"observation": observation, "pnl_adopted": False},
            },
        )
        print(json.dumps({"updated_trade": updated, "slot_released": released}, default=str))
    finally:
        close_method = getattr(exchange, "close", None)
        if callable(close_method):
            close_method()


if __name__ == "__main__":
    main()
