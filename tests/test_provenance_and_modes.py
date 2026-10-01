from types import SimpleNamespace

import pandas as pd

from bot.core.provenance import FieldSource, FillDetails, QueryOutcome, QueryResult
from bot.config import Config
from bot.strategies.scalping import ScalpingStrategy
from bot.signals.signal_engine import SignalEngine


def test_fill_is_not_pnl_eligible_when_fee_is_unknown():
    fill = FillDetails(
        price=100.0,
        price_source=FieldSource.EXCHANGE_FILL,
        quantity=1.0,
        quantity_source=FieldSource.EXCHANGE_FILL,
        fee=0.0,
        fee_source=FieldSource.UNCONFIRMED,
    )
    assert not fill.is_pnl_eligible
    assert not fill.is_fee_confirmed
    assert fill.price_source.value == "exchange_fill"


def test_query_result_distinguishes_empty_from_failure():
    assert QueryResult.from_items([]).outcome is QueryOutcome.SUCCESS_EMPTY
    assert QueryResult.failed("timeout").outcome is QueryOutcome.FAILED


def test_scalping_reads_explicit_risk_settings():
    cfg = Config()
    cfg.risk.scalp_take_profit_pct = 0.007
    cfg.risk.scalp_stop_loss_pct = 0.002
    strategy = ScalpingStrategy(cfg)
    assert strategy.target_profit_pct == 0.007
    assert strategy.max_stop_loss_pct == 0.002


def test_hunter_is_an_aggregate_mode_not_a_fake_strategy():
    cfg = SimpleNamespace(active_mode="HUNTER")
    engine = SignalEngine(cfg)
    assert engine.active_mode == "HUNTER"
    assert engine.scalping_strategy is not None
    assert engine.explosion_detector is not None


def test_ema200_requires_full_warmup():
    from bot.signals.indicators import IndicatorCalculator

    df = pd.DataFrame({"close": range(1, 201)})
    ema = IndicatorCalculator.calculate_ema(df, period=200)
    assert ema.iloc[:-1].isna().all()
    assert pd.notna(ema.iloc[-1])


def test_strategy_router_preserves_scalping_exit_levels():
    from bot.strategies.router import StrategyRouter

    class Filters:
        def validate_signal(self, action, latest, df):
            return True

    class Scalp:
        config = SimpleNamespace(risk=SimpleNamespace(default_sl_pct=1.5, tp1_pct=1.0, tp2_pct=2.5))
        max_stop_loss_pct = 0.003
        target_profit_pct = 0.005

        def evaluate_scalp_setup(self, df, symbol):
            return {"action": "BUY", "stop_loss": 99.7, "take_profit": 100.5}

    class NoExplosion:
        def detect(self, df, symbol):
            return None

    router = StrategyRouter("SCALPING", Filters(), NoExplosion(), Scalp())
    decision = router.evaluate(pd.DataFrame([{"close": 100, "volume": 10, "rsi": 30, "macd": 1, "macd_signal": 0}]), "BTC/USDT")
    assert decision["stop_loss"] == 99.7
    assert decision["take_profit_1"] == 100.5
