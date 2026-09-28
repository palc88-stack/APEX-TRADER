from bot.config import Config
from bot.signals.filters import SignalFilters
from bot.signals.signal_engine import SignalEngine


def test_filter_thresholds_are_loaded_from_risk_config(monkeypatch):
    monkeypatch.setenv("MAX_RSI_BUY", "30")
    monkeypatch.setenv("MIN_RSI_SELL", "70")
    monkeypatch.setenv("MIN_VOLUME_RATIO", "2.5")
    cfg = Config()

    filters = SignalFilters(cfg)

    assert filters.max_rsi_buy == 30.0
    assert filters.min_rsi_sell == 70.0
    assert filters.min_volume_ratio == 2.5


def test_signal_engine_uses_nested_risk_config(monkeypatch):
    monkeypatch.setenv("MAX_RSI_BUY", "31")
    monkeypatch.setenv("MIN_RSI_SELL", "69")
    monkeypatch.setenv("MIN_VOLUME_RATIO", "1.75")
    engine = SignalEngine(Config())

    assert engine.signal_filters.max_rsi_buy == 31.0
    assert engine.signal_filters.min_rsi_sell == 69.0
    assert engine.signal_filters.min_volume_ratio == 1.75
