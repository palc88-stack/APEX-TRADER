# bot/signals/signal_engine.py - الكود المُصحَّح
import pandas as pd
from typing import Dict, Any, Optional
from enum import Enum
from loguru import logger

from bot.signals.indicators import IndicatorCalculator, TechnicalIndicators
from bot.signals.filters import SignalFilters
from bot.strategies.explosion import ExplosionDetector, ExplosionSignal
from bot.strategies.scalping import ScalpingStrategy


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeSignal:
    """
    ✅ إضافة is_valid و side لتوافق main.py
    """
    def __init__(
        self,
        symbol: str,
        action: str,
        price: float,
        confidence: float,
        strategy: str,
        reason: str
    ):
        self.symbol = symbol
        self.action = action
        self.price = price
        self.confidence = confidence
        self.strategy = strategy
        self.reason = reason

    @property
    def is_valid(self) -> bool:
        """✅ دالة مفقودة - يستخدمها main.py"""
        return (
            self.action not in (TradeDirection.HOLD, "HOLD")
            and self.confidence >= 0.65
            and self.price > 0
        )

    @property
    def side(self) -> str:
        """✅ توحيد الاتجاه لـ buy/sell لـ exchange.place_order()"""
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
    """
    ✅ محرك الإشارات المُحسَّن - يدمج Explosion و Scalping.
    """

    def __init__(self, config: Optional[Any] = None):
        self.config = config
        cfg_dict = config.__dict__ if hasattr(config, "__dict__") else {}
        self.indicator_calculator = IndicatorCalculator(cfg_dict)
        self.signal_filters = SignalFilters(cfg_dict)
        # ✅ ربط الـ strategies الآن داخل المحرك
        self.explosion_detector = ExplosionDetector()
        self.scalping_strategy = ScalpingStrategy(cfg_dict)

    def evaluate_market(
        self,
        df: Optional[pd.DataFrame],
        symbol: str
    ) -> Dict[str, Any]:
        """
        تقييم حالة السوق وإرجاع dict للإشارة.
        ✅ يدمج منطق Scalping مع منطق الاتجاه.
        """
        result = {
            "symbol": symbol,
            "action": TradeDirection.HOLD,
            "strategy": None,
            "confidence": 0.0,
            "indicators": {},
            "reason": "No valid signal detected",
        }

        if df is None or df.empty or len(df) < 50:
            logger.warning(
                "⚠️ بيانات غير كافية للتحليل: {}", symbol
            )
            return result

        try:
            df_analyzed = self.indicator_calculator.calculate_all(df)
            if df_analyzed is None or df_analyzed.empty:
                return result

            latest = df_analyzed.iloc[-1]
            close = float(latest.get("close", 0.0))
            rsi = float(latest.get("rsi", 50.0))
            ema_200 = float(latest.get("ema_200", close))
            bb_upper = float(latest.get("bb_upper", close))
            bb_lower = float(latest.get("bb_lower", close))

            result["indicators"] = {
                "close": close,
                "rsi": rsi,
                "ema_200": ema_200,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
            }

            is_trend_bullish = close > ema_200
            is_trend_bearish = close < ema_200

            # ─ 1. ExplosionDetector: أعلى أولوية ─
            explosion_signal = self.explosion_detector.detect(
                df_analyzed, symbol
            )
            if explosion_signal and explosion_signal.is_valid:
                direction = "BUY" if explosion_signal.direction == "LONG" else "SELL"
                if self.signal_filters.validate_signal(direction, latest):
                    result.update({
                        "action": explosion_signal.direction,
                        "strategy": "EXPLOSION",
                        "confidence": explosion_signal.confidence,
                        "reason": explosion_signal.reason
                    })
                    logger.info(
                        "🚀 Explosion detected for {}: {} (confidence={:.2f})",
                        symbol, direction, explosion_signal.confidence
                    )
                    return result

            # ─ 2. ScalpingStrategy ─
            scalp_result = self.scalping_strategy.evaluate_scalp_setup(
                df_analyzed, symbol
            )
            if scalp_result["action"] != "HOLD":
                action_dir = scalp_result["action"]
                if self.signal_filters.validate_signal(action_dir, latest):
                    result.update({
                        "action": action_dir,
                        "strategy": "SCALPING",
                        "confidence": 0.80 if action_dir == "BUY" else 0.75,
                        "reason": scalp_result["reason"]
                    })
                    logger.info(
                        "⚡ Scalping signal for {}: {} | entry={} sl={} tp={}",
                        symbol, action_dir,
                        scalp_result["entry_price"],
                        scalp_result["stop_loss"],
                        scalp_result["take_profit"]
                    )
                    return result

            # ─ Scalping: أولوية لاستراتيجية البولنجر ─
            if close <= bb_lower and rsi < 35:
                if self.signal_filters.validate_signal("BUY", latest):
                    result.update({
                        "action": TradeDirection.LONG,
                        "strategy": "SCALPING_BUY",
                        "confidence": 0.80,
                        "reason": "Lower BB touch + RSI oversold.",
                    })
                    return result

            elif close >= bb_upper and rsi > 65:
                if self.signal_filters.validate_signal("SELL", latest):
                    result.update({
                        "action": TradeDirection.SHORT,
                        "strategy": "SCALPING_SELL",
                        "confidence": 0.80,
                        "reason": "Upper BB touch + RSI overbought.",
                    })
                    return result

            # ─ Trend Bounce: استراتيجية الاتجاه ─
            if is_trend_bullish and rsi < 40:
                if self.signal_filters.validate_signal("BUY", latest):
                    result.update({
                        "action": TradeDirection.LONG,
                        "strategy": "TREND_BOUNCE",
                        "confidence": 0.85,
                        "reason": "Bullish trend pullback + RSI oversold.",
                    })
            elif is_trend_bearish and rsi > 60:
                if self.signal_filters.validate_signal("SELL", latest):
                    result.update({
                        "action": TradeDirection.SHORT,
                        "strategy": "TREND_PULLBACK",
                        "confidence": 0.85,
                        "reason": "Bearish trend rally + RSI overbought.",
                    })

            return result

        except Exception as e:
            logger.error(
                "❌ SignalEngine error for {}: {}", symbol, e
            )
            return result
