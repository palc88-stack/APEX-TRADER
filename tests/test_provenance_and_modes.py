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
