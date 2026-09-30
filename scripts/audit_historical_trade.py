"""Audit a historical Binance Testnet trade using exchange-confirmed fills only.

This command is read-only by default. It prints the exact order, related fills,
and nearby symbol fills needed to repair a historical ledger row; it never
infers fees from candles and never mutates Supabase.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import ccxt


def compact_fill(trade: dict) -> dict:
    return {
        "id": trade.get("id"),
        "order": trade.get("order"),
        "side": trade.get("side"),
        "amount": trade.get("amount"),
        "price": trade.get("price"),
        "cost": trade.get("cost"),
        "timestamp": trade.get("timestamp"),
        "fee": trade.get("fee"),
        "info": trade.get("info") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-id", default=os.getenv("HISTORICAL_TRADE_ID", "328600480"))
    parser.add_argument("--symbol", default=os.getenv("HISTORICAL_SYMBOL", "SOON/USDT:USDT"))
    args = parser.parse_args()

    exchange = ccxt.binanceusdm({
        "apiKey": os.environ["BINANCE_API_KEY"],
        "secret": os.environ["BINANCE_SECRET_KEY"],
        "enableRateLimit": True,
        "options": {"defaultType": "future", "adjustForTimeDifference": True},
    })
    exchange.set_sandbox_mode(True)
    try:
        exchange.load_markets()
        order = exchange.fetch_order(args.trade_id, args.symbol)
        trades = exchange.fetch_my_trades(args.symbol, limit=100)
        related = [t for t in trades if str(t.get("order") or "") == str(args.trade_id)]
        order_timestamp = int(order.get("timestamp") or 0)
        nearby = [
            t for t in trades
            if order_timestamp - 60_000 <= int(t.get("timestamp") or 0) <= order_timestamp + 86_400_000
        ]
        payload = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "symbol": args.symbol,
            "order_id": str(args.trade_id),
            "order": {
                "status": order.get("status"),
                "side": order.get("side"),
                "filled": order.get("filled"),
                "average": order.get("average"),
                "timestamp": order.get("timestamp"),
                "fee": order.get("fee"),
                "info": order.get("info") or {},
            },
            "fills": [compact_fill(t) for t in related],
            "nearby_symbol_fills": [compact_fill(t) for t in nearby],
        }
        print(json.dumps(payload, indent=2, default=str))
        if not related:
            raise RuntimeError("No exchange fills found; historical ledger must remain unconfirmed")
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
