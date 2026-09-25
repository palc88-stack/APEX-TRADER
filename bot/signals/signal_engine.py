import pandas as pd
from typing import Dict, Any, Optional
from loguru import logger

from bot.signals.indicators import IndicatorCalculator
from bot.signals.filters import SignalFilters


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
        تقييم حالة السوق الحية للرمز المالي واستخراج إشارات التداول الحقيقية
        بناءً على الشموع والمؤشرات الفنية المعتمدة.
        """
        result = {
            "symbol": symbol,
            "action": "HOLD",  # BUY, SELL, HOLD
            "strategy": None,
            "confidence": 0.0,
            "indicators": {},
            "reason": "No valid signal detected"
        }

        if df is None or df.empty or len(df) < 50:
            logger.warning("⚠️ بيانات غير كافية للتحليل الفني للرمز: {}", symbol)
            return result

        try:
            # 1. حساب المؤشرات الفنية الحقيقية على إطار البيانات
            df_analyzed = self.indicator_calculator.calculate_all(df)
            if df_analyzed is None or df_analyzed.empty:
                return result

            # استخراج آخر شمعة مكتملة للتقييم
            latest_row = df_analyzed.iloc[-1]
            prev_row = df_analyzed.iloc[-2]

            close_price = float(latest_row.get('close', 0.0))
            rsi = float(latest_row.get('rsi', 50.0))
            ema_50 = float(latest_row.get('ema_50', close_price))
            ema_200 = float(latest_row.get('ema_200', close_price))

            result["indicators"] = {
                "close": close_price,
                "rsi": rsi,
                "ema_50": ema_50,
                "ema_200": ema_200
            }

            # 2. تطبيق فلاتر السوق الحقيقية (اتجاه السوق والزخم)
            is_trend_bullish = close_price > ema_200
            is_trend_bearish = close_price < ema_200

            # 3. تقييم شروط الدخول الحقيقية (كمثال مبني على الاتجاه والزخم الفعلي)
            if is_trend_bullish and rsi < 40:
                # إشارة شراء حقيقية بناءً على ارتداد في اتجاه صاعد عام
                if self.signal_filters.validate_signal("BUY", latest_row):
                    result["action"] = "BUY"
                    result["strategy"] = "TREND_BOUNCE"
                    result["confidence"] = 0.85
                    result["reason"] = "Bullish trend pullback with RSI oversold recovery."

            elif is_trend_bearish and rsi > 60:
                # إشارة بيع حقيقية بناءً على ارتداد في اتجاه هابط عام
                if self.signal_filters.validate_signal("SELL", latest_row):
                    result["action"] = "SELL"
                    result["strategy"] = "TREND_PULLBACK"
                    result["confidence"] = 0.85
                    result["reason"] = "Bearish trend rally with RSI overbought rejection."

            logger.debug("🔍 تحليل الإشارة للرمز {} => النتيجة: {} ({})", symbol, result["action"], result["reason"])
            return result

        except Exception as error:
            logger.error("❌ خطأ في محرك الإشارات أثناء تقييم الرمز {}: {}", symbol, error)
            return result
