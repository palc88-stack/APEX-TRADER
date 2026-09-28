"""Deterministic strategy arbitration for the HUNTER aggregate mode."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from loguru import logger


class StrategyRouter:
    """Evaluate strategies once and emit at most one validated decision."""

    PRIORITY = {"EXPLOSION": 0, "HUNTER": 1, "SCALPING": 2}

    def __init__(self, mode: str, filters: Any, explosion_detector: Any, scalping_strategy: Any):
        self.mode = str(mode or "HUNTER").upper()
        self.filters = filters
        self.explosion_detector = explosion_detector
        self.scalping_strategy = scalping_strategy

    def evaluate(self, df: Optional[pd.DataFrame], symbol: str) -> Optional[dict[str, Any]]:
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        candidates: list[dict[str, Any]] = []

        if self.mode in {"HUNTER", "EXPLOSION"}:
            explosion = self.explosion_detector.detect(df, symbol)
            if explosion and explosion.is_valid:
                action = "BUY" if explosion.direction == "LONG" else "SELL"
                if self._passes_filters(action, latest, df):
                    candidates.append({
                        "action": explosion.direction,
                        "strategy": "EXPLOSION",
                        "confidence": explosion.confidence,
                        "reason": explosion.reason,
                    })

        if self.mode == "HUNTER":
            hunter = self._hunter_candidate(latest, df)
            if hunter:
                candidates.append(hunter)

        if self.mode in {"HUNTER", "SCALPING"}:
            scalp = self.scalping_strategy.evaluate_scalp_setup(df, symbol)
            action = str(scalp.get("action", "HOLD")).upper()
            if action != "HOLD" and self._passes_filters(action, latest, df):
                candidates.append({
                    "action": action,
                    "strategy": "SCALPING",
                    "confidence": 0.80 if action == "BUY" else 0.75,
                    "reason": scalp.get("reason", "Validated scalping setup"),
                })

        if not candidates:
            return None
        candidates.sort(key=lambda item: self.PRIORITY.get(item["strategy"], 99))
        decision = candidates[0]
        logger.debug(
            "StrategyRouter selected {} for {} ({} candidates)",
            decision["strategy"], symbol, len(candidates),
        )
        return decision

    def _hunter_candidate(self, latest: pd.Series, df: pd.DataFrame) -> Optional[dict[str, Any]]:
        close = float(latest.get("close", 0.0))
        ema_200 = float(latest.get("ema_200", close))
        rsi = float(latest.get("rsi", 50.0))
        if close > ema_200 and rsi < 40 and self._passes_filters("BUY", latest, df):
            return {
                "action": "LONG",
                "strategy": "HUNTER",
                "confidence": 0.85,
                "reason": "Bullish trend pullback + RSI oversold.",
            }
        if close < ema_200 and rsi > 60 and self._passes_filters("SELL", latest, df):
            return {
                "action": "SHORT",
                "strategy": "HUNTER",
                "confidence": 0.85,
                "reason": "Bearish trend rally + RSI overbought.",
            }
        return None

    def _passes_filters(self, action: str, latest: pd.Series, df: pd.DataFrame) -> bool:
        return bool(self.filters.validate_signal(action, latest, df))
