# bot/signals/filters.py - الكود المُصحَّح
import pandas as pd
from typing import Dict, Any, Optional
from loguru import logger


class SignalFilters:
    """
    ✅ فلاتر مُحسَّنة:
    - عتبات RSI متوافقة مع signal_engine
    - فلتر Volume نسبي (يعتمد على متوسط الحجم لا قيمة ثابتة)
    - إضافة فلتر MACD للتأكيد
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # ✅ توحيد العتبات مع signal_engine:
        # BUY عند rsi < 40 → max_rsi_buy يجب أن يكون >= 40
        self.max_rsi_buy = float(self.config.get("max_rsi_buy", 42.0))
        # SELL عند rsi > 60 → min_rsi_sell يجب أن يكون <= 60
        self.min_rsi_sell = float(self.config.get("min_rsi_sell", 58.0))
        # ✅ نسبة الحجم: الشمعة الحالية >= X ضعف متوسط الحجم
        self.min_volume_ratio = float(self.config.get("min_volume_ratio", 0.5))

    def validate_signal(
        self,
        action: str,
        latest_row: pd.Series,
        df: Optional[pd.DataFrame] = None
    ) -> bool:
        if latest_row is None or latest_row.empty:
            logger.warning("⚠️ بيانات فارغة - رُفضت الإشارة.")
            return False

        try:
            volume = float(latest_row.get("volume", 0.0))
            close = float(latest_row.get("close", 0.0))
            rsi = float(latest_row.get("rsi", 50.0))
            macd = float(latest_row.get("macd", 0.0))
            macd_signal = float(latest_row.get("macd_signal", 0.0))

            # 1. ✅ فلتر الحجم النسبي
            if df is not None and "volume" in df.columns and len(df) >= 20:
                avg_volume = float(df["volume"].tail(20).mean())
                if avg_volume > 0:
                    volume_ratio = volume / avg_volume
                    if volume_ratio < self.min_volume_ratio:
                        logger.debug(
                            "⚠️ حجم منخفض: {:.2f}x المتوسط", volume_ratio
                        )
                        return False
            elif volume <= 0 or (close > 0 and volume * close < 500):
                logger.debug("⚠️ حجم غير كافٍ: {}", volume)
                return False

            action_upper = action.upper()

            # 2. ✅ فلتر RSI
            if action_upper == "BUY":
                if rsi > self.max_rsi_buy:
                    logger.debug("⚠️ RSI مرتفع للشراء: {:.1f}", rsi)
                    return False
                # ✅ تأكيد MACD للشراء
                if macd < macd_signal:
                    logger.debug("⚠️ MACD يؤكد الاتجاه الهبوطي - رُفض BUY")
                    return False

            elif action_upper == "SELL":
                if rsi < self.min_rsi_sell:
                    logger.debug("⚠️ RSI منخفض للبيع: {:.1f}", rsi)
                    return False
                # ✅ تأكيد MACD للبيع
                if macd > macd_signal:
                    logger.debug("⚠️ MACD يؤكد الاتجاه الصعودي - رُفض SELL")
                    return False

            else:
                return False

            logger.info(
                "✅ الإشارة اجتازت الفلاتر: {} | RSI={:.1f} | Vol={:.0f}",
                action, rsi, volume
            )
            return True

        except Exception as e:
            logger.error("❌ خطأ في validate_signal: {}", e)
            return False
