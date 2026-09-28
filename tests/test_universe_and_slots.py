from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bot.data.universe_manager import UniverseManager
from bot.data.state_manager import StateManager


class FakeExchange:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    async def fetch_liquid_symbols(self, limit=20, quote="USDT"):
        self.calls += 1
        return self.candidates[:limit]


class FakeState:
    def __init__(self):
        self.active = []
        self.snapshots = []

    def get_active_universe_symbols(self):
        return self.active

    def replace_universe_snapshot(self, snapshot_id, rows, expires_at):
        self.snapshots.append((snapshot_id, rows, expires_at))
        self.active = rows


def config(symbols=("BTC/USDT",)):
    return SimpleNamespace(
        trading=SimpleNamespace(
            symbols=list(symbols), universe_size=3,
            universe_refresh_hours=4, universe_quote="USDT",
        )
    )


@pytest.mark.asyncio
async def test_universe_refreshes_and_limits_symbols():
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    exchange = FakeExchange([
        {"symbol": "BTC/USDT", "quote_volume_24h": 1000},
        {"symbol": "ETH/USDT", "quote_volume_24h": 900},
        {"symbol": "SOL/USDT", "quote_volume_24h": 800},
        {"symbol": "XRP/USDT", "quote_volume_24h": 700},
    ])
    state = FakeState()
    manager = UniverseManager(exchange, state, config(), clock=lambda: now)

    symbols = await manager.refresh_if_due(force=True)

    assert symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    assert exchange.calls == 1
    assert len(state.snapshots) == 1
    assert manager.get_symbols_for_cycle(["DOGE/USDT"]) == [
        "DOGE/USDT", "BTC/USDT", "ETH/USDT"
    ]


@pytest.mark.asyncio
async def test_universe_uses_persisted_snapshot_before_refresh():
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    exchange = FakeExchange([])
    state = FakeState()
    state.active = [{
        "symbol": "ETH/USDT", "rank": 1,
        "expires_at": "2026-09-28T22:00:00+00:00",
    }]
    manager = UniverseManager(exchange, state, config(), clock=lambda: now)

    assert await manager.refresh_if_due() == ["ETH/USDT"]
    assert exchange.calls == 0


@pytest.mark.asyncio
async def test_universe_falls_back_without_destroying_configured_symbols():
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    exchange = FakeExchange([])
    state = FakeState()
    manager = UniverseManager(exchange, state, config(("BTC/USDT",)), clock=lambda: now)

    assert await manager.refresh_if_due(force=True) == ["BTC/USDT"]


class FakeRpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class FakeClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        data = [{"slot_no": 1, "symbol": params.get("p_symbol"), "reservation_id": params.get("p_reservation_id")}]
        return FakeRpc(data)


def test_slot_methods_use_atomic_rpc_contract():
    manager = object.__new__(StateManager)
    manager.client = FakeClient()

    slot = manager.try_reserve_position_slot("BTC/USDT", "owner", "reservation", 3)
    assert slot["slot_no"] == 1
    assert manager.bind_position_slot("reservation", "trade-1") is True
    assert manager.release_position_slot(trade_id="trade-1") is True
    assert [name for name, _ in manager.client.calls] == [
        "reserve_position_slot", "bind_position_slot", "release_position_slot"
    ]
