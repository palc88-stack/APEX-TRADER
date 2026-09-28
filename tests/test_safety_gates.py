from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.core.exchange import ExchangeManager, ExchangeSafetyError

ROOT = Path(__file__).resolve().parents[1]


def exchange_config(testnet: bool):
    return SimpleNamespace(
        primary_exchange=lambda: "binance",
        binance_api_key="",
        binance_secret_key="",
        binance_testnet=testnet,
    )


def test_live_requires_explicit_gate(monkeypatch):
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    with pytest.raises(ExchangeSafetyError):
        ExchangeManager(SimpleNamespace(exchange=exchange_config(False)))


def test_non_binance_is_rejected(monkeypatch):
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    cfg = exchange_config(True)
    cfg.primary_exchange = lambda: "bybit"
    with pytest.raises(ExchangeSafetyError):
        ExchangeManager(SimpleNamespace(exchange=cfg))


@pytest.mark.asyncio
async def test_account_mutations_are_blocked_by_default(monkeypatch):
    monkeypatch.delenv("TRADING_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("ALLOW_NEW_ENTRIES", raising=False)
    manager = ExchangeManager(SimpleNamespace(exchange=exchange_config(True)))

    with pytest.raises(ExchangeSafetyError, match="TRADING_EXECUTION_ENABLED"):
        await manager.place_order(
            symbol="BTC/USDT", side="buy", amount=0.001,
            price=50000, stop_loss=49000, take_profit=51000,
        )

    with pytest.raises(ExchangeSafetyError, match="TRADING_EXECUTION_ENABLED"):
        await manager.reduce_only_close("BTC/USDT", 0.001)


@pytest.mark.asyncio
async def test_new_entries_can_be_disabled_while_execution_remains_available(monkeypatch):
    monkeypatch.setenv("TRADING_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("ALLOW_NEW_ENTRIES", "false")
    manager = ExchangeManager(SimpleNamespace(exchange=exchange_config(True)))

    with pytest.raises(ExchangeSafetyError, match="ALLOW_NEW_ENTRIES"):
        await manager.place_order(
            symbol="BTC/USDT", side="buy", amount=0.001,
            price=50000, stop_loss=49000, take_profit=51000,
        )


@pytest.mark.asyncio
async def test_testnet_adapter_closes_without_network(monkeypatch):
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    manager = ExchangeManager(SimpleNamespace(exchange=exchange_config(True)))
    await manager.close()


def test_worker_has_no_service_key_fallback():
    worker = (ROOT / "src/worker.js").read_text()
    assert "SUPABASE_SERVICE_KEY" not in worker
    assert "ASSETS.fetch" in worker
    assert "pending_signals" not in worker
    assert "WEBHOOK_SECRET" not in worker


@pytest.mark.asyncio
async def test_binance_protection_uses_algo_order_api():
    class FakeExchange:
        def __init__(self):
            self.calls = []

        def market(self, symbol):
            assert symbol == "BTC/USDT"
            return {"id": "BTCUSDT"}

        def milliseconds(self):
            return 1700000000000

        async def request(self, path, api, method, params):
            self.calls.append((path, api, method, params))
            return {"algoId": len(self.calls)}

    manager = object.__new__(ExchangeManager)
    manager._exchange = FakeExchange()
    manager._markets_loaded = True

    ids = await manager._create_protection("BTC/USDT", "sell", 0.01, 90000, 80000)

    assert ids == {"1", "2"}
    assert [call[0:3] for call in manager._exchange.calls] == [
        ("algoOrder", "fapiPrivate", "POST"),
        ("algoOrder", "fapiPrivate", "POST"),
    ]
    for _, _, _, params in manager._exchange.calls:
        assert params["algoType"] == "CONDITIONAL"
        assert params["symbol"] == "BTCUSDT"
        assert params["reduceOnly"] == "true"
        assert params["type"] in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}
        assert "triggerPrice" in params


def test_workflow_has_no_schedule_or_live_secret():
    workflow = (ROOT / ".github/workflows/binance.yml").read_text()
    assert "\n  schedule:" not in workflow
    assert 'ALLOW_LIVE_TRADING: "false"' in workflow
    assert 'BINANCE_TESTNET: "true"' in workflow
    assert 'TRADING_EXECUTION_ENABLED: "false"' in workflow
    assert 'ALLOW_NEW_ENTRIES: "false"' in workflow


def test_testnet_session_scans_required_symbols_by_real_volume():
    workflow = (ROOT / ".github/workflows/testnet-session.yml").read_text()
    assert "TRADING_SYMBOLS: BTC/USDT,ETH/USDT,SOL/USDT" in workflow
    assert 'AUTO_SYMBOL_SCAN: "true"' in workflow
    assert 'SYMBOL_SCAN_LIMIT: "3"' in workflow
    assert 'MIN_QUOTE_VOLUME_USDT: "5000000"' in workflow
