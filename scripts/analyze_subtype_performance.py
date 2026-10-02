"""Read-only subtype performance analyzer for confirmed Testnet trades.

The script never calls Binance and never writes to Supabase. It reads confirmed
closed trades, groups them by strategy_subtype, and emits a milestone report
whenever the closed-trade count reaches another multiple of 10.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from supabase import Client, create_client


DEFAULT_BATCH_SIZE = 10


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_WRITE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_WRITE_KEY/SUPABASE_SERVICE_ROLE_KEY are required")
    return create_client(url, key)


def summarize_trades(trades: list[dict[str, Any]], batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    confirmed = [
        trade for trade in trades
        if str(trade.get("status") or "").upper() == "CLOSED"
        and str(trade.get("pnl_source") or "").lower() == "exchange_fill"
        and trade.get("pnl") is not None
    ]
    by_subtype: dict[str, list[dict[str, Any]]] = {}
    for trade in confirmed:
        subtype = str(trade.get("strategy_subtype") or "unknown")
        by_subtype.setdefault(subtype, []).append(trade)

    subtype_reports: list[dict[str, Any]] = []
    for subtype, rows in sorted(by_subtype.items()):
        pnls = [as_float(row.get("pnl")) for row in rows]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        subtype_reports.append({
            "strategy_subtype": subtype,
            "closed_trades": len(rows),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(rows), 6) if rows else 0.0,
            "realized_pnl": round(sum(pnls), 8),
            "average_win": round(gross_profit / len(wins), 8) if wins else 0.0,
            "average_loss": round(sum(losses) / len(losses), 8) if losses else 0.0,
            "gross_profit": round(gross_profit, 8),
            "gross_loss": round(gross_loss, 8),
            "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss else None,
            "expectancy": round(sum(pnls) / len(rows), 8) if rows else 0.0,
            "average_exit_slippage_bps": round(
                sum(as_float(row.get("exit_slippage_bps")) for row in rows) / len(rows), 8
            ) if rows else 0.0,
        })

    closed_count = len(confirmed)
    completed_milestone = (closed_count // batch_size) * batch_size
    next_milestone = completed_milestone + batch_size
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "environment": "binance_testnet",
        "confirmed_closed_trades": closed_count,
        "completed_milestone": completed_milestone,
        "next_milestone": next_milestone,
        "milestone_reached": completed_milestone > 0,
        "subtypes": subtype_reports,
    }


def run(output: Path | None = None, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    client = build_supabase()
    rows = client.table("trades").select(
        "id,status,strategy,strategy_subtype,pnl,pnl_source,exit_slippage_bps,closed_at"
    ).eq("status", "CLOSED").eq("pnl_source", "exchange_fill").not_.is_("pnl", "null").limit(10000).execute().data or []
    report = summarize_trades(rows, batch_size=batch_size)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    try:
        return run(args.output, args.batch_size)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
