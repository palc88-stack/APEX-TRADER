"""Read-only Binance Testnet ↔ Supabase consistency verifier.

The command never creates, changes, cancels, or closes exchange orders and never
writes to Supabase. It compares open exchange positions with OPEN/
NEEDS_RECONCILIATION rows, position slots, bot heartbeat, and today's confirmed
PnL projection. It exits non-zero when a blocking mismatch is found.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ccxt
from supabase import Client, create_client


QTY_TOLERANCE_RATIO = 0.001  # 0.1%, matching the Cloudflare reconciliation logic.
MIN_QTY = 1e-12


def normalize_symbol(value: Any) -> str:
    raw = str(value or "").upper().split(":", 1)[0]
    return "".join(ch for ch in raw if ch.isalnum())


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def position_quantity(position: dict[str, Any]) -> float:
    """Read a CCXT position quantity, with Binance raw-info fallback."""
    for key in ("contracts", "contractSize"):
        value = position.get(key)
        if key == "contractSize" and position.get("contracts") is not None:
            continue
        if value is not None and as_float(value) != 0:
            return abs(as_float(value))
    info = position.get("info") or {}
    return abs(as_float(info.get("positionAmt")))


def expected_trade_quantity(trade: dict[str, Any]) -> float:
    remaining = trade.get("remaining_quantity")
    if remaining is not None and as_float(remaining) > MIN_QTY:
        return as_float(remaining)
    return as_float(trade.get("entry_quantity"))


def quantity_matches(expected: float, actual: float) -> bool:
    if expected <= MIN_QTY or actual <= MIN_QTY:
        return expected <= MIN_QTY and actual <= MIN_QTY
    return abs(expected - actual) <= max(MIN_QTY, expected * QTY_TOLERANCE_RATIO)


def compare_positions(
    db_trades: list[dict[str, Any]], exchange_positions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    db_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for trade in db_trades:
        db_by_symbol.setdefault(normalize_symbol(trade.get("symbol")), []).append(trade)

    exchange_by_symbol = {
        normalize_symbol(position.get("symbol")): position
        for position in exchange_positions
        if position_quantity(position) > MIN_QTY
    }

    for symbol_key, trades in db_by_symbol.items():
        exchange = exchange_by_symbol.get(symbol_key)
        expected = sum(expected_trade_quantity(trade) for trade in trades)
        if exchange is None:
            findings.append({
                "type": "db_trade_without_exchange_position",
                "symbol": trades[0].get("symbol"),
                "expected_quantity": expected,
                "trade_ids": [trade.get("id") for trade in trades],
            })
            continue
        actual = position_quantity(exchange)
        if not quantity_matches(expected, actual):
            findings.append({
                "type": "quantity_mismatch",
                "symbol": trades[0].get("symbol"),
                "expected_quantity": expected,
                "exchange_quantity": actual,
                "trade_ids": [trade.get("id") for trade in trades],
            })

    for symbol_key, position in exchange_by_symbol.items():
        if symbol_key not in db_by_symbol:
            findings.append({
                "type": "exchange_position_without_db_trade",
                "symbol": position.get("symbol"),
                "exchange_quantity": position_quantity(position),
            })
    return findings


def build_exchange() -> Any:
    if os.getenv("BINANCE_TESTNET", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("Refusing to run: BINANCE_TESTNET must be true")
    if os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("Refusing to run: ALLOW_LIVE_TRADING must be false")
    api_key = os.environ.get("BINANCE_API_KEY")
    secret = os.environ.get("BINANCE_SECRET_KEY")
    if not api_key or not secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_SECRET_KEY are required")
    exchange = ccxt.binanceusdm({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future", "adjustForTimeDifference": True},
    })
    exchange.set_sandbox_mode(True)
    return exchange


def build_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_WRITE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_WRITE_KEY/SUPABASE_SERVICE_ROLE_KEY are required")
    return create_client(url, key)


def read_supabase(client: Client) -> dict[str, Any]:
    trades = client.table("trades").select(
        "id,symbol,status,entry_quantity,remaining_quantity,pnl,pnl_source"
    ).in_("status", ["OPEN", "NEEDS_RECONCILIATION"]).limit(100).execute().data or []
    slots = client.table("position_slots").select(
        "slot_no,symbol,trade_id,reservation_id,status"
    ).in_("status", ["reserved", "occupied"]).limit(100).execute().data or []
    state = client.table("bot_state").select(
        "id,is_running,bot_status,environment,heartbeat_at,last_run_at,cycle_completed_at,"
        "daily_realized_pnl,daily_loss_used_usd,risk_day,updated_at"
    ).eq("id", 1).limit(1).execute().data or []
    summary = client.table("dashboard_daily_summary").select(
        "risk_day,confirmed_closed_trades,confirmed_realized_pnl,confirmed_loss_used_usd,confirmed_fees"
    ).limit(1).execute().data or []
    return {
        "trades": trades,
        "slots": slots,
        "bot_state": state[0] if state else None,
        "daily_summary": summary[0] if summary else None,
    }


def validate_slots(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    trades = snapshot["trades"]
    trade_ids = {str(trade.get("id")) for trade in trades}
    for slot in snapshot["slots"]:
        status = str(slot.get("status") or "")
        trade_id = slot.get("trade_id")
        if status == "occupied" and trade_id and str(trade_id) not in trade_ids:
            findings.append({
                "type": "occupied_slot_without_open_trade",
                "slot_no": slot.get("slot_no"),
                "trade_id": trade_id,
                "symbol": slot.get("symbol"),
            })
    return findings


def validate_pnl(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    state = snapshot.get("bot_state") or {}
    summary = snapshot.get("daily_summary") or {}
    findings: list[dict[str, Any]] = []
    state_pnl = as_float(state.get("daily_realized_pnl"))
    summary_pnl = as_float(summary.get("confirmed_realized_pnl"))
    state_loss = as_float(state.get("daily_loss_used_usd"))
    summary_loss = as_float(summary.get("confirmed_loss_used_usd"))
    if abs(state_pnl - summary_pnl) > 0.01:
        findings.append({"type": "bot_state_pnl_mismatch", "bot_state": state_pnl, "summary": summary_pnl})
    if abs(state_loss - summary_loss) > 0.01:
        findings.append({"type": "bot_state_loss_mismatch", "bot_state": state_loss, "summary": summary_loss})
    return findings


def run(output: Path | None = None) -> int:
    checked_at = datetime.now(timezone.utc).isoformat()
    exchange = build_exchange()
    try:
        exchange.load_markets()
        exchange_positions = exchange.fetch_positions()
        client = build_supabase()
        snapshot = read_supabase(client)
        findings = compare_positions(snapshot["trades"], exchange_positions)
        findings.extend(validate_slots(snapshot))
        findings.extend(validate_pnl(snapshot))
        report = {
            "checked_at": checked_at,
            "mode": "read_only",
            "environment": "binance_testnet",
            "exchange_open_count": sum(position_quantity(p) > MIN_QTY for p in exchange_positions),
            "supabase_open_trade_count": len(snapshot["trades"]),
            "occupied_or_reserved_slot_count": len(snapshot["slots"]),
            "findings": findings,
            "snapshot": snapshot,
        }
        rendered = json.dumps(report, indent=2, ensure_ascii=False, default=str)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 1 if findings else 0
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    try:
        return run(args.output)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
