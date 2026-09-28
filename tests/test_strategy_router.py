from types import SimpleNamespace

import pandas as pd

from bot.strategies.router import StrategyRouter


class FakeFilters:
    def __init__(self):
        self.calls = []

    def validate_signal(self, action, latest, df=None):
        self.calls.append((action, latest, df))
        return df is not None


class FakeExplosion:
    def __init__(self, valid=True):
        self.is_valid = valid
        self.direction = "LONG"
        self.confidence = 0.9
        self.reason = "explosion"


class FakeExplosionDetector:
    def __init__(self, signal=None):
        self.signal = signal

    def detect(self, df, symbol):
        return self.signal


class FakeScalping:
    def __init__(self, action="BUY"):
        self.action = action

    def evaluate_scalp_setup(self, df, symbol):
        return {"action": self.action, "reason": "scalp"}


def frame():
    return pd.DataFrame({
        "close": [101.0], "ema_200": [100.0], "rsi": [35.0],
        "volume": [1000.0],
    })


def test_explosion_has_priority_over_hunter_and_scalping():
    filters = FakeFilters()
    router = StrategyRouter(
        "HUNTER", filters,
        FakeExplosionDetector(FakeExplosion()),
        FakeScalping("BUY"),
    )

    result = router.evaluate(frame(), "BTC/USDT")

    assert result["strategy"] == "EXPLOSION"
    assert result["action"] == "LONG"
    assert all(call[2] is not None for call in filters.calls)


def test_hunter_has_priority_over_scalping_when_no_explosion():
    router = StrategyRouter(
        "HUNTER", FakeFilters(),
        FakeExplosionDetector(None),
        FakeScalping("BUY"),
    )

    result = router.evaluate(frame(), "BTC/USDT")

    assert result["strategy"] == "HUNTER"
    assert result["action"] == "LONG"


def test_scalping_mode_does_not_run_hunter():
    router = StrategyRouter(
        "SCALPING", FakeFilters(),
        FakeExplosionDetector(FakeExplosion()),
        FakeScalping("BUY"),
    )

    result = router.evaluate(frame(), "BTC/USDT")

    assert result["strategy"] == "SCALPING"
    assert result["action"] == "BUY"


def test_no_valid_candidate_returns_none():
    router = StrategyRouter(
        "HUNTER", FakeFilters(),
        FakeExplosionDetector(None),
        FakeScalping("HOLD"),
    )
    data = frame()
    data["close"] = [99.0]
    data["rsi"] = [50.0]

    assert router.evaluate(data, "BTC/USDT") is None
