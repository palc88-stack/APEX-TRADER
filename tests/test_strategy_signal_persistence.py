"""Unit coverage for the StateManager signal-attribution write path.

Uses a stub Supabase client so the test never contacts external services and
never writes to the database.
"""
from bot.data.state_manager import StateManager


class _StubResult:
    def __init__(self, data):
        self.data = data


class _StubInsert:
    def __init__(self, log, table, payload, on_conflict=None):
        self._log = log
        self._table = table
        self._payload = payload
        self._on_conflict = on_conflict

    def execute(self):
        self._log.append((self._table, self._payload, self._on_conflict))
        return _StubResult([{"id": "signal-id"}])


class _StubUpsert(_StubInsert):
    pass


class _StubTable:
    def __init__(self, log, table):
        self._log = log
        self._table = table

    def insert(self, payload):
        return _StubInsert(self._log, self._table, payload)

    def upsert(self, payload, on_conflict=None):
        return _StubUpsert(self._log, self._table, payload, on_conflict)


class _StubClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _StubTable(self.calls, name)


def test_record_strategy_signal_persists_attribution_fields():
    manager = StateManager.__new__(StateManager)
    client = _StubClient()
    manager.client = client

    ok = manager.record_strategy_signal({
        "id": "00000000-0000-0000-0000-000000000001",
        "idempotency_key": "signal:BTC/USDT:USDT:candle:trend_pullback_long:LONG",
        "symbol": "BTC/USDT:USDT",
        "strategy": "TREND",
        "strategy_subtype": "trend_pullback_long",
        "action": "LONG",
        "atr_value": 120.5,
        "atr_multiplier": 2.0,
        "risk_budget_usd": 10.0,
        "status": "candidate",
    })

    assert ok is True
    table, payload, on_conflict = client.calls[0]
    assert table == "strategy_signals"
    assert on_conflict == "idempotency_key"
    assert payload["strategy_subtype"] == "trend_pullback_long"
    assert payload["status"] == "candidate"
    assert payload["atr_value"] == 120.5


def test_record_strategy_signal_failure_is_non_fatal():
    manager = StateManager.__new__(StateManager)

    class _BrokenClient:
        def table(self, name):
            raise RuntimeError("schema not migrated yet")

    manager.client = _BrokenClient()

    # Attribution failures must never abort the market cycle or place a
    # different order as a side effect.
    assert manager.record_strategy_signal({"idempotency_key": "x"}) is False