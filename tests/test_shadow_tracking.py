import pandas as pd

from bot.learning.shadow import build_shadow_observation, update_shadow_outcome


def frame():
    index = pd.date_range("2026-01-01", periods=25, freq="5min", tz="UTC")
    close = [100.0] * 24 + [98.0]
    return pd.DataFrame({
        "open": close,
        "high": [v + 0.5 for v in close],
        "low": [v - 0.5 for v in close],
        "close": close,
        "volume": [100.0] * 25,
        "ema_50": [100.0] * 25,
        "ema_200": [100.0] * 25,
        "rsi": [50.0] * 24 + [34.0],
        "macd": [0.0] * 25,
        "macd_signal": [0.0] * 25,
        "atr_value": [1.0] * 25,
        "bb_upper": [101.0] * 25,
        "bb_middle": [100.0] * 25,
        "bb_lower": [99.0] * 24 + [98.5],
    }, index=index)


def test_shadow_observation_is_idempotent_and_observational():
    result = build_shadow_observation(
        frame(), {"action": "HOLD", "confidence": 0.0},
        "BTC/USDT:USDT", "5m",
    )
    assert result["classification"] in {"NO_SIGNAL", "NEAR_MISS", "SHADOW_CANDIDATE"}
    assert result["idempotency_key"]
    assert result["model_version"] == "shadow-rules-v2"
    assert "pnl" not in result


def test_shadow_long_hits_stop_without_realized_pnl():
    data = frame()
    observation = build_shadow_observation(
        data, {"action": "LONG", "confidence": 0.8,
               "stop_loss": 99.0, "take_profit_1": 102.0},
        "BTC/USDT:USDT", "5m",
    )
    outcome = update_shadow_outcome(observation, data.tail(1))
    assert outcome["status"] in {"LOST", "OPEN"}
    assert "realized_pnl" not in outcome
