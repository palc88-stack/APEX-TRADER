from types import SimpleNamespace

import pandas as pd

from bot.core.provenance import FieldSource, FillDetails
from bot.core.risk_manager import RiskManager
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
