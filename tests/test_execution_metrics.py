from types import SimpleNamespace

import pandas as pd

from bot.core.provenance import FieldSource, FillDetails
from bot.core.risk_manager import RiskManager
from bot.config import Config
from bot.signals.indicators import IndicatorCalculator
from bot.strategies.router import StrategyRouter


def test_fill_details_preserves_execution_metrics():
    fill = FillDetails(
        price=101.0,
        price_source=FieldSource.EXCHANGE_FILL,
        quantity=2.0,
        quantity_source=FieldSource.EXCHANGE_FILL,
        fee=0.2,
        fee_source=FieldSource.EXCHANGE_FILL,
        fee_currency="USDT",
        filled_at="2026-09-30T10:00:00+00:00",
        reference_price=100.0,
        slippage_bps=100.0,
        mark_price=100.8,
        trigger_price=101.0,
        trade_ids=("fill-1",),
    )
    record = fill.as_record()
    assert record["fee_currency"] == "USDT"
    assert record["trade_ids"] == ["fill-1"]
    assert record["slippage_bps"] == 100.0
    assert record["mark_price"] == 100.8


def test_router_emits_strategy_subtype_for_hunter():
    class Filters:
        def validate_signal(self, action, latest, df):
            return True

    class Explosion:
        def detect(self, df, symbol):
            return None

    class Scalp:
        def evaluate_scalp_setup(self, df, symbol):
            return {"action": "HOLD"}

    router = StrategyRouter("HUNTER", Filters(), Explosion(), Scalp())
    df = pd.DataFrame({"close": [101.0], "ema_200": [100.0], "rsi": [35.0]})
    decision = router.evaluate(df, "BTC/USDT")
    assert decision["strategy"] == "HUNTER"
    assert decision["strategy_subtype"] == "trend_pullback_long"
    assert decision["rule_score"] == decision["confidence"]


def test_risk_manager_sizes_are_bounded_by_stop_distance():
    config = SimpleNamespace(
        risk=SimpleNamespace(
            max_risk_per_trade_pct=2.0,
            max_leverage=20,
            min_confidence=0.65,
        )
    )
    manager = RiskManager(config)
    assert manager.max_risk_per_trade_pct == 0.02
    assert manager.evaluate_risk(
        account_balance=1000,
        size_usd=50,
        leverage=20,
        entry_price=100,
        stop_loss=99,
        direction="buy",
    )
    assert not manager.evaluate_risk(
        account_balance=1000,
        size_usd=200,
        leverage=20,
        entry_price=100,
        stop_loss=99,
        direction="buy",
    )


def test_risk_manager_rejects_legacy_leverage_above_configured_limit():
    config = SimpleNamespace(
        risk=SimpleNamespace(
            max_risk_per_trade_pct=2.0,
            max_leverage=5,
            min_confidence=0.65,
        )
    )
    manager = RiskManager(config)
    assert not manager.evaluate_risk(
        account_balance=1000,
        size_usd=10,
        leverage=20,
        entry_price=100,
        stop_loss=99,
        direction="buy",
    )


def test_risk_manager_rejects_zero_stop_distance_and_invalid_leverage():
    config = SimpleNamespace(
        risk=SimpleNamespace(
            max_risk_per_trade_pct=2.0,
            max_leverage=5,
            min_confidence=0.65,
        )
    )
    manager = RiskManager(config)
    assert not manager.evaluate_risk(
        account_balance=1000,
        size_usd=10,
        leverage=5,
        entry_price=100,
        stop_loss=100,
        direction="buy",
    )
    assert not manager.evaluate_risk(
        account_balance=1000,
        size_usd=10,
        leverage=0,
        entry_price=100,
        stop_loss=99,
        direction="buy",
    )


def test_atr_is_available_after_warmup():
    frame = pd.DataFrame({
        "open": [100.0 + i for i in range(20)],
        "high": [101.0 + i for i in range(20)],
        "low": [99.0 + i for i in range(20)],
        "close": [100.5 + i for i in range(20)],
        "volume": [1000.0] * 20,
    })
    result = IndicatorCalculator().calculate_all(frame)
    assert result["atr_value"].iloc[:13].isna().all()
    assert result["atr_value"].iloc[-1] > 0


def test_atr_position_size_uses_dollar_risk_and_leverage():
    bot = object.__new__(__import__("bot.main", fromlist=["ApexTraderBot"]).ApexTraderBot)
    bot._current_balance = 1000.0
    bot.config = Config()
    bot.config.risk.max_risk_per_trade_usd = 10.0
    bot.config.risk.max_risk_per_trade_pct = 2.0
    bot.config.risk.max_position_pct = 10.0
    # Entry 100, ATR stop distance 2*1.5 = 3; notional = 10 / 3 * 100.
    margin = bot._calculate_position_size(
        entry_price=100.0,
        stop_loss=97.0,
        leverage=5,
        account_balance=1000.0,
    )
    assert margin == 66.67


def test_position_sizing_fails_closed_when_inputs_are_invalid():
    bot = object.__new__(__import__("bot.main", fromlist=["ApexTraderBot"]).ApexTraderBot)
    bot._current_balance = 1000.0
    bot.config = Config()
    assert bot._calculate_position_size(
        entry_price=0.0,
        stop_loss=0.0,
        leverage=5,
        account_balance=1000.0,
    ) == 0.0
