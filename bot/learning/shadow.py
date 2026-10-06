"""Observation-only Shadow Mode helpers.

This module never authorizes an order and never produces realized PnL.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd


MODEL_VERSION = "shadow-rules-v2"


def _num(row: Any, name: str, default: float = 0.0) -> float:
    try:
        value = row.get(name, default)
        return float(value) if pd.notna(value) else default
    except (TypeError, ValueError):
        return default


def build_shadow_observation(
    df: pd.DataFrame,
    signal: Dict[str, Any],
    symbol: str,
    timeframe: str,
    *,
    horizon_candles: int = 12,
) -> Dict[str, Any]:
    """Build a closed-candle paper observation from real market data."""
    latest = df.iloc[-1]
    close = _num(latest, "close")
    high = _num(latest, "high", close)
    low = _num(latest, "low", close)
    ema200 = _num(latest, "ema_200", close)
    rsi = _num(latest, "rsi", 50.0)
    macd = _num(latest, "macd")
    macd_signal = _num(latest, "macd_signal")
    atr = _num(latest, "atr_value")
    upper = _num(latest, "bb_upper", close)
    lower = _num(latest, "bb_lower", close)
    middle = _num(latest, "bb_middle", close)
    bb_range = upper - lower
    bb_position = (close - lower) / bb_range if bb_range > 0 else 0.5
    bb_width = bb_range / middle if middle > 0 else 0.0
    volume = _num(latest, "volume")
    avg_volume = float(df["volume"].tail(20).mean()) if "volume" in df and len(df) >= 20 else 0.0
    volume_ratio = volume / avg_volume if avg_volume > 0 else 0.0

    risk = getattr(getattr(signal, "config", None), "risk", None)
    # The router's current strategy contracts are explicit and deterministic.
    buy_rsi = 40.0
    sell_rsi = 60.0
    scalp_buy_rsi = 35.0
    scalp_sell_rsi = 65.0
    volume_min = 0.5

    checks_long = {
        "hunter_trend": close > ema200,
        "hunter_rsi": rsi < buy_rsi,
        "filter_volume": volume_ratio >= volume_min,
        "filter_macd": macd >= macd_signal,
    }
    checks_short = {
        "hunter_trend": close < ema200,
        "hunter_rsi": rsi > sell_rsi,
        "filter_volume": volume_ratio >= volume_min,
        "filter_macd": macd <= macd_signal,
    }
    scalp_buy = close <= lower and rsi < scalp_buy_rsi
    scalp_sell = close >= upper and rsi > scalp_sell_rsi

    action = str(signal.get("action") or "HOLD").upper()
    if action.startswith("TRADEDIRECTION."):
        action = action.split(".", 1)[1]
    if action in {"LONG", "BUY"}:
        direction = "LONG"
        checks = checks_long
    elif action in {"SHORT", "SELL"}:
        direction = "SHORT"
        checks = checks_short
    elif close > ema200:
        direction = "LONG"
        checks = checks_long
    elif close < ema200:
        direction = "SHORT"
        checks = checks_short
    else:
        direction = "LONG"
        checks = checks_long

    checks = dict(checks)
    checks["scalping_setup"] = scalp_buy if direction == "LONG" else scalp_sell
    passed = sum(bool(value) for value in checks.values())
    score = round(passed / len(checks), 4) if checks else 0.0
    failed_rules = [name for name, ok in checks.items() if not ok]
    if action in {"LONG", "BUY", "SHORT", "SELL"} and score >= 0.70:
        classification = "SHADOW_CANDIDATE"
    elif score >= 0.45:
        classification = "NEAR_MISS"
    else:
        classification = "NO_SIGNAL"

    ts = latest.get("timestamp", df.index[-1])
    candle_time = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    strategy = signal.get("strategy") or "ROUTER"
    subtype = signal.get("strategy_subtype") or "none"
    candidate_action = direction if action == "HOLD" else action
    return {
        "idempotency_key": f"{symbol}:{timeframe}:{candle_time}:{strategy}:{subtype}:{candidate_action}",
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": strategy,
        "strategy_subtype": subtype,
        "candle_closed_at": candle_time,
        "candidate_action": candidate_action,
        "classification": classification,
        "model_version": MODEL_VERSION,
        "confidence": float(signal.get("confidence") or 0.0),
        "rule_score": float(signal.get("rule_score") or score),
        "entry_price": close,
        "stop_loss": signal.get("stop_loss"),
        "take_profit_1": signal.get("take_profit_1"),
        "take_profit_2": signal.get("take_profit_2"),
        "atr_value": atr or None,
        "atr_pct": (atr / close * 100.0) if close > 0 else None,
        "rsi": rsi,
        "ema_50": _num(latest, "ema_50", close),
        "ema_200": ema200,
        "macd": macd,
        "macd_signal": macd_signal,
        "bb_position": bb_position,
        "bb_width": bb_width,
        "volume_ratio": volume_ratio,
        "failed_rules": failed_rules,
        "features": {"checks": checks, "near_miss_score": score, "high": high, "low": low},
        "horizon_candles": max(1, int(horizon_candles)),
    }


def update_shadow_outcome(row: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """Advance one open paper observation using only newer closed candles."""
    if df is None or df.empty:
        return {}
    try:
        signal_time = pd.Timestamp(row.get("candle_closed_at"))
        signal_time = (
            signal_time.tz_localize("UTC")
            if signal_time.tzinfo is None
            else signal_time.tz_convert("UTC")
        )
        if "timestamp" in df.columns:
            candle_times = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            frame = df[candle_times > signal_time]
        else:
            frame = df[df.index > signal_time]
    except (TypeError, ValueError):
        frame = df
    if frame.empty:
        return {"status": "OPEN", "mfe_pct": None, "mae_pct": None}
    entry = float(row.get("entry_price") or 0.0)
    if entry <= 0:
        return {"status": "INSUFFICIENT_DATA"}
    direction = str(row.get("candidate_action") or "LONG").upper()
    long = direction in {"LONG", "BUY"}
    sl = float(row.get("stop_loss") or (entry * (0.985 if long else 1.015)))
    tp = float(row.get("take_profit_1") or (entry * (1.01 if long else 0.99)))
    highs = pd.to_numeric(frame["high"], errors="coerce")
    lows = pd.to_numeric(frame["low"], errors="coerce")
    mfe = ((highs.max() - entry) / entry * 100.0) if long else ((entry - lows.min()) / entry * 100.0)
    mae = ((lows.min() - entry) / entry * 100.0) if long else ((highs.max() - entry) / entry * 100.0)
    status = "OPEN"
    exit_reason = None
    for _, candle in frame.iterrows():
        high, low = float(candle["high"]), float(candle["low"])
        if (long and low <= sl) or ((not long) and high >= sl):
            status, exit_reason = "LOST", "stop_loss"
            break
        if (long and high >= tp) or ((not long) and low <= tp):
            status, exit_reason = "WON", "take_profit_1"
            break
    return {"status": status, "mfe_pct": mfe, "mae_pct": mae, "exit_reason": exit_reason}


def recommend_shadow_action(signal: Dict[str, Any], *, min_confidence: float = 0.65) -> Dict[str, Any]:
    """Backward-compatible observation-only recommendation."""
    action = str(signal.get("action") or "HOLD").upper()
    confidence = float(signal.get("confidence") or 0.0)
    indicators = signal.get("indicators") or {}
    valid = action in {"BUY", "SELL", "LONG", "SHORT"} and float(indicators.get("atr_value") or 0) > 0
    recommendation = action if valid and confidence >= min_confidence else "HOLD"
    return {
        "candidate_action": action,
        "candidate_confidence": confidence,
        "shadow_action": recommendation,
        "shadow_confidence": confidence if recommendation != "HOLD" else 0.0,
        "decision": "observation_only",
        "reason": "rules-v1 observation; no adaptive model applied",
        # Keep the legacy event contract stable; shadow_signals uses v2.
        "model_version": "shadow-rules-v1",
    }
