# bot/signals/signal_engine.py
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

import pandas as pd
from loguru import logger

from bot.signals.filters import SignalFilters
from bot.signals.indicators import IndicatorCalculator
from bot.strategies.explosion import ExplosionDetector
from bot.strategies.router import StrategyRouter
from bot.strategies.scalping import ScalpingStrategy


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeSignal:
    def __init__(
        self,
        symbol: str,
        action: str,
        price: float,
        confidence: float,
        strategy: str,
        reason: str,
    ):
        self.symbol = symbol
        self.action = action
        self.price = price
        self.confidence = confidence
        self.strategy = strategy
        self.reason = reason

    @property
    def is_valid(self) -> bool:
        return (
            self.action not in (TradeDirection.HOLD, "HOLD")
            and self.confidence >= 0.65
            and self.price > 0
        )

    @property
    def side(self) -> str:
        action_upper = str(self.action).upper()
        if action_upper in ("LONG", "BUY"):
            return "buy"
        if action_upper in ("SHORT", "SELL"):
            return "sell"
        return "hold"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "price": self.price,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "reason": self.reason,
        }


class SignalEngine:
    """Calculate indicators and delegate arbitration to one deterministic router."""

    def __init__(self, config: Optional[Any] = None):
        self.config = config
        cfg_dict = config.__dict__ if hasattr(config, "__dict__") else {}
        self.active_mode = str(getattr(config, "active_mode", "HUNTER")).upper()
        self.indicator_calculator = IndicatorCalculator(cfg_dict)
        self.signal_filters = SignalFilters(getattr(config, "risk", cfg_dict))
        self.explosion_detector = ExplosionDetector()
        self.scalping_strategy = ScalpingStrategy(config)
        self.strategy_router = StrategyRouter(
            self.active_mode,
            self.signal_filters,
            self.explosion_detector,
            self.scalping_strategy,
        )

    def evaluate_market(self, df: Optional[pd.DataFrame], symbol: str) -> Dict[str, Any]:
        result = {
            "symbol": symbol,
            "action": TradeDirection.HOLD,
            "strategy": None,
            "mode": self.active_mode,
            "confidence": 0.0,
            "indicators": {},
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "reason": "No valid signal detected",
        }

        # EMA200 لا يكون صالحًا قبل اكتمال 200 شمعة مغلقة.
        if df is None or df.empty or len(df) < 200:
            logger.warning("⚠️ بيانات غير كافية للتحليل/تدفئة EMA200: {}", symbol)
            return result

        try:
            df_analyzed = self.indicator_calculator.calculate_all(df)
            if df_analyzed is None or df_analyzed.empty:
                return result

            latest = df_analyzed.iloc[-1]
            close = float(latest.get("close", 0.0))
            result["indicators"] = {
                "close": close,
                "rsi": float(latest.get("rsi", 50.0)),
                "ema_200": float(latest.get("ema_200", close)),
                "bb_upper": float(latest.get("bb_upper", close)),
                "bb_lower": float(latest.get("bb_lower", close)),
            }

            decision = self.strategy_router.evaluate(df_analyzed, symbol)
            if decision:
                result.update({
                    "action": decision["action"],
                    "strategy": decision["strategy"],
                    "mode": self.active_mode,
                    "confidence": decision["confidence"],
                    "stop_loss_pct": decision.get("stop_loss_pct"),
                    "take_profit_pct": decision.get("take_profit_pct"),
                    "reason": decision["reason"],
                })
                logger.info(
                    "✅ StrategyRouter signal for {}: {} via {} (confidence={:.2f})",
                    symbol, decision["action"], decision["strategy"], decision["confidence"],
                )
            return result
        except Exception as error:
            logger.error("❌ SignalEngine error for {}: {}", symbol, error)
            return result
