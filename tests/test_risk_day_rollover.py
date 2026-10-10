from __future__ import annotations

import pytest

from bot.main import ApexTraderBot
from bot.data.state_manager import StateManager


class StateManagerStub:
    def __init__(self, metrics, persist=True):
        self.metrics = metrics
        self.persist = persist
        self.update_calls = []

    def get_daily_confirmed_metrics(self):
        return self.metrics

    async def update_bot_status(self, **kwargs):
        self.update_calls.append(kwargs)
        return self.persist


def make_bot(state_manager):
    bot = object.__new__(ApexTraderBot)
    bot._risk_day = "2026-10-09"
    bot._daily_loss_used = 2.33
    bot._daily_realized_pnl = -2.33
    bot._current_balance = 4894.23
    bot._daily_loss_limit = 195.77
    bot.state_manager = state_manager
    return bot


@pytest.mark.asyncio
async def test_rollover_uses_confirmed_metrics_and_persists_new_utc_day():
    state = StateManagerStub({"loss_used": 0.0, "realized_pnl": 0.0})
    bot = make_bot(state)

    changed = await bot._roll_risk_day_if_needed("2026-10-10")

    assert changed is True
    assert bot._risk_day == "2026-10-10"
    assert bot._daily_loss_used == 0.0
    assert bot._daily_realized_pnl == 0.0
    assert state.update_calls == [
        {
            "balance": 4894.23,
            "daily_loss_used": 0.0,
            "daily_realized_pnl": 0.0,
            "daily_loss_limit": 195.77,
            "risk_day": "2026-10-10",
        }
    ]


@pytest.mark.asyncio
async def test_rollover_does_nothing_when_utc_day_is_unchanged():
    state = StateManagerStub(None)
    bot = make_bot(state)

    changed = await bot._roll_risk_day_if_needed("2026-10-09")

    assert changed is False
    assert bot._daily_loss_used == 2.33
    assert state.update_calls == []


@pytest.mark.asyncio
async def test_rollover_fails_closed_when_confirmed_metrics_are_unavailable():
    state = StateManagerStub(None)
    bot = make_bot(state)

    with pytest.raises(RuntimeError, match="confirmed daily risk metrics unavailable"):
        await bot._roll_risk_day_if_needed("2026-10-10")

    assert bot._risk_day == "2026-10-09"
    assert bot._daily_loss_used == 2.33
    assert state.update_calls == []


@pytest.mark.asyncio
async def test_rollover_reverts_memory_and_fails_closed_when_persistence_fails():
    state = StateManagerStub({"loss_used": 0.0, "realized_pnl": 0.0}, persist=False)
    bot = make_bot(state)

    with pytest.raises(RuntimeError, match="could not persist daily risk rollover"):
        await bot._roll_risk_day_if_needed("2026-10-10")

    assert bot._risk_day == "2026-10-09"
    assert bot._daily_loss_used == 2.33
    assert bot._daily_realized_pnl == -2.33
    assert len(state.update_calls) == 1


class FakeTable:
    def __init__(self, raises=False):
        self.raises = raises
        self.payload = None

    def upsert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self.raises:
            raise RuntimeError("database unavailable")


class FakeClient:
    def __init__(self, table):
        self.fake_table = table

    def table(self, _name):
        return self.fake_table


@pytest.mark.asyncio
async def test_state_manager_reports_successful_status_write():
    table = FakeTable()
    manager = object.__new__(StateManager)
    manager.client = FakeClient(table)

    result = await manager.update_bot_status(risk_day="2026-10-10")

    assert result is True
    assert table.payload["risk_day"] == "2026-10-10"


@pytest.mark.asyncio
async def test_state_manager_reports_failed_status_write():
    manager = object.__new__(StateManager)
    manager.client = FakeClient(FakeTable(raises=True))

    result = await manager.update_bot_status(risk_day="2026-10-10")

    assert result is False


@pytest.mark.asyncio
async def test_state_manager_reports_missing_client():
    manager = object.__new__(StateManager)
    manager.client = None

    assert await manager.update_bot_status(risk_day="2026-10-10") is False
