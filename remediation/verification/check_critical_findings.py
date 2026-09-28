"""Static safety checks for the current APEX-TRADER implementation.

This script is offline-only: it reads source files and never connects to an
exchange, Supabase, Telegram, or any other external service.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


main = read("bot/main.py")
exchange = read("bot/core/exchange.py")
config = read("bot/config.py")
provenance = read("bot/core/provenance.py")
schema = read("database/schema.sql").lower()
worker = read("src/worker.js")
testnet_workflow = read(".github/workflows/testnet-session.yml")

# Live trading must be explicitly enabled and testnet must be the default.
assert "ALLOW_LIVE_TRADING" in config and "False" in config
assert "not self.is_testnet and not self.allow_live" in exchange
assert "binance_testnet" in config and "True" in config

# Protection orders must use the Algo Order API and be reduce-only.
assert '"algoOrder"' in exchange
assert '"reduceOnly": "true"' in exchange
assert "STOP_MARKET" in exchange and "TAKE_PROFIT_MARKET" in exchange

# Execution accounting must use exchange-derived fills and fail closed.
assert "fetch_fill_details" in exchange
assert "FieldSource.EXCHANGE_FILL" in provenance
assert "NEEDS_RECONCILIATION" in main
assert "pnl_source" in main

# Persistent state must protect the partial execution table and trade states.
assert "enable row level security" in schema
assert "partial_closes" in schema
assert "needs_reconciliation" in schema

# The public Worker is dashboard-only; no webhook or service-key fallback.
assert "ASSETS.fetch" in worker
assert "pending_signals" not in worker
assert "WEBHOOK_SECRET" not in worker
assert "SUPABASE_SERVICE_KEY" not in worker

# The bounded Testnet workflow must remain explicitly safe.
assert 'BINANCE_TESTNET: "true"' in testnet_workflow
assert 'ALLOW_LIVE_TRADING: "false"' in testnet_workflow
assert "TRADING_SYMBOLS: BTC/USDT,ETH/USDT,SOL/USDT" in testnet_workflow
assert 'SYMBOL_SCAN_LIMIT: "3"' in testnet_workflow

print("Current safety gates verified without network access or secrets.")
