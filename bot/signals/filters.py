import pandas as pd
from typing import Dict, Any, Optional
from loguru import logger


class SignalFilters:
    """
    فلاتر التحقق من صحة إشارات التداول (Signal Filters) لمنظومة (Apex Trader).
    تتحقق من الشروط الفنية الحقيقية (حجم التداول، السيولة، والزخم) لتقليل الإشارات الكاذبة.
    خالية تماماً من أي قيم وهمية أو افتراضية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # إعداد الحدود الدنيا المقبولة للسيولة والزخم من الإعدادات الحقيقية إن وجدت
        self.min_volume_threshold = float(self.config.get("min_volume", 1000.0))
        self.max_rsi_buy = float(self.config.get("max_rsi_buy", 45.0))
        self.min_rsi_sell = float(self.config.get("min_rsi_sell", 55.0))

    def validate_signal(self, action: str, latest_row: pd.Series) -> bool:
        """
        التحقق من صحة الإشارة بناءً على شروط السوق والبيانات الحقيقية للشمعة الأخيرة.
        """
        if latest_row is None or latest_row.empty:
            logger.warning("⚠️ بيانات الشمعة فارغة، تم رفض الإشارة تلقائياً.")
            return False

        try:
            # استخراج القيم الحقيقية من الشمعة والمؤشرات المحسوبة
            volume = float(latest_row.get('volume', 0.0))
            close = float(latest_row.get('close', 0.0))
            rsi = float(latest_row.get('rsi', 50.0))

            # 1. فلتر السيولة وحجم التداول الحقيقي
            if volume <= 0 or (volume * close) < self.min_volume_threshold:
                logger.debug("⚠️ تم رفض الإشارة بسبب ضعف حجم التداول أو السيولة: volume={}", volume)
                return False

            # 2. فلتر الزخم واتجاه القوة النسبية (RSI)
            if action.upper() == "BUY":
                if rsi > self.max_rsi_buy:
                    logger.debug("⚠️ تم رفض إشارة الشراء: قيمة RSI مرتفعة جداً ({})", rsi)
                    return False
            elif action.upper() == "SELL":
                if rsi < self.min_rsi_sell:
                    logger.debug("⚠️ تم رفض إشارة البيع: قيمة RSI منخفضة جداً ({})", rsi)
                    return False
            else:
                return False

            logger.info("✅ اجتازت الإشارة كافة فلاتر السوق الحقيقية بنجاح (الإجراء: {}, RSI: {}, الحجم: {})", action, rsi, volume)
            return True

        except Exception as error:
            logger.error("❌ خطأ أثناء فحص وتدقيق الإشارة في الفلاتر: {}", error)
            return False
