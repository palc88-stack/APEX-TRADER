import pandas as pd
from typing import Dict, Any, Optional
from enum import Enum
from loguru import logger

from bot.signals.indicators import IndicatorCalculator, TechnicalIndicators
from bot.signals.filters import SignalFilters


class TradeDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradingMode(str, Enum):
    LIVE = "LIVE"
    TESTNET = "TESTNET"


class TradeSignal:
    """
    نموذج كلاس إشارة التداول الحقيقية المتكاملة لمنظومة (Apex Trader).
    """
    def __init__(self, symbol: str, action: str, price: float, confidence: float, strategy: str, reason: str):
        self.symbol = symbol
        self.action = action
        self.price = price
        self.confidence = confidence
        self.strategy = strategy
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "price": self.price,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "reason": self.reason
        }


class SignalEngine:
    """
    محرك الإشارات الرئيسي (Signal Engine) لمنظومة التداول الآلي (Apex Trader).
    يقوم بتحليل تدفقات السوق الحية عبر المؤشرات والفلاتر الاستراتيجية بدقة صارمة.
    خالٍ تماماً من أي قيم أو إشارات وهمية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.indicator_calculator = IndicatorCalculator(self.config)
        self.signal_filters = SignalFilters(self.config)

    def evaluate_market(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        """
        تقييم حالة السوق الحية للرمز المالي واستخراج إشارات التداول الحقيقية.
        """
        result = {
            "symbol": symbol,
            "action": TradeDirection.HOLD,
            "strategy": None,
            "confidence": 0.0,
            "indicators": {},
            "reason": "No valid signal detected"
        }

        if df is None or df.empty or len(df) < 50:
            logger.warning("⚠️ بيانات غير كافية للتحليل الفني للرمز: {}", symbol)
            return result

        try:
            df_analyzed = self.indicator_calculator.calculate_all(df)
            if df_analyzed is None or df_analyzed.empty:
                return result

            latest_row = df_analyzed.iloc[-1]
            close_price = float(latest_row.get('close', 0.0))
            rsi = float(latest_row.get('rsi', 50.0))
            ema_200 = float(latest_row.get('ema_200', close_price))

            result["indicators"] = {
                "close": close_price,
                "rsi": rsi,
                "ema_200": ema_200
            }

            is_trend_bullish = close_price > ema_200
            is_trend_bearish = close_price < ema_200

            if is_trend_bullish and rsi < 40:
                if self.signal_filters.validate_signal("BUY", latest_row):
                    result["action"] = TradeDirection.BUY
                    result["strategy"] = "TREND_BOUNCE"
                    result["confidence"] = 0.85
                    result["reason"] = "Bullish trend pullback with RSI oversold recovery."

            elif is_trend_bearish and rsi > 60:
                if self.signal_filters.validate_signal("SELL", latest_row):
                    result["action"] = TradeDirection.SELL
                    result["strategy"] = "TREND_PULLBACK"
                    result["confidence"] = 0.85
                    result["reason"] = "Bearish trend rally with RSI overbought rejection."

            return result

        except Exception as error:
            logger.error("❌ خطأ في محرك الإشارات أثناء تقييم الرمز {}: {}", symbol, error)
            return result
