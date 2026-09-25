# bot/signals/filters.py - الكود المُصحَّح
import pandas as pd
from typing import Dict, Any, Optional, Union
from loguru import logger


class SignalFilters:
    """
    ✅ فلاتر مُحسَّنة:
    - عتبات RSI متوافقة مع signal_engine
    - فلتر Volume نسبي (يعتمد على متوسط الحجم لا قيمة ثابتة)
    - إضافة فلتر MACD للتأكيد
    - متوافق مع كلاً من Dict config و Config dataclass object
    """

    def __init__(self, config: Optional[Union[Dict[str, Any], "Config"]] = None):
        self.config = config
        # قراءة عتبات الفلاتر — تدعم كل من dict و Config object
        if config is None:
            self.max_rsi_buy = 42.0
            self.min_rsi_sell = 58.0
            self.min_volume_ratio = 0.5
        elif isinstance(config, dict):
            self.max_rsi_buy = float(config.get("max_rsi_buy", 42.0))
            self.min_rsi_sell = float(config.get("min_rsi_sell", 58.0))
            self.min_volume_ratio = float(config.get("min_volume_ratio", 0.5))
        else:
            # Config dataclass object — يستخدم config.get() التي تقرأ من env vars
            self.max_rsi_buy = float(config.get("max_rsi_buy", 42.0))
            self.min_rsi_sell = float(config.get("min_rsi_sell", 58.0))
            self.min_volume_ratio = float(config.get("min_volume_ratio", 0.5))

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
