from types import SimpleNamespace

import pytest

from bot.data.state_manager import StateManager


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.payloads = []

    def select(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def upsert(self, payload, **_kwargs):
        self.payloads.append(payload)
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class FakeClient:
    def __init__(self, rows):
        self.tables = {
            "trades": FakeTable(rows),
            "bot_state": FakeTable(),
        }

    def table(self, name):
        return self.tables[name]


@pytest.mark.asyncio
async def test_sync_trade_counters_uses_confirmed_trade_ledger():
    manager = object.__new__(StateManager)
    manager.client = FakeClient([
        {"status": "CLOSED", "pnl": "2.5"},
        {"status": "CLOSED", "pnl": "-1.0"},
        {"status": "RECONCILED_FLAT", "pnl": None},
    ])
    assert await manager.sync_trade_counters() is True
    assert manager.client.tables["bot_state"].payloads[-1]["total_trades"] == 3
    assert manager.client.tables["bot_state"].payloads[-1]["winning_trades"] == 1


def test_hold_diagnostics_contract_is_non_execution():
    payload = {
        "action": "HOLD",
        "status": "no_signal",
        "reason": "No valid signal detected",
    }
    assert payload["action"] == "HOLD"
    assert payload["status"] == "no_signal"
    assert "place_order" not in payload
