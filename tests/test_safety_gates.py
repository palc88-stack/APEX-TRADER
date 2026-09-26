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


def test_workflow_has_no_schedule_or_live_secret():
    workflow = (ROOT / ".github/workflows/binance.yml").read_text()
    assert "\n  schedule:" not in workflow
    assert 'ALLOW_LIVE_TRADING: "false"' in workflow
    assert 'BINANCE_TESTNET: "true"' in workflow
