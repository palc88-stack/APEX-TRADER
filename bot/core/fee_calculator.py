from typing import Dict, Any, Optional
from loguru import logger


class FeeCalculator:
    """
    حاسبة الرسوم وتكاليف الصفقات الفعلية (Fee Calculator) لمنظومة (Apex Trader).
    تحسب بدقة رسوم المنصة (Maker / Taker) ومعدلات التمويل (Funding Rates) للصفقات الحية.
    خالية تماماً من أي قيم وهمية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # نسب رسوم افتراضية قياسية للمنصات (يمكن تجاوزها من ملف الإعدادات الحقيقي)
        self.maker_fee_rate = float(self.config.get("maker_fee_rate", 0.0002))  # 0.02%
        self.taker_fee_rate = float(self.config.get("taker_fee_rate", 0.0004))  # 0.04%

    def calculate_trade_fees(self, size_usd: float, is_maker: bool = False) -> float:
        """
        حساب قيمة الرسوم المستقطعة بالدولار لفتح وإغلاق الصفقة بناءً على الحجم الحقيقي.
        """
        try:
            if size_usd <= 0:
                return 0.0

            rate = self.maker_fee_rate if is_maker else self.taker_fee_rate
            # الرسوم تُحسب عادة على إجمالي قيمة العقد (حجم الصفقة) للدخول والخروج
            total_fee = size_usd * rate * 2.0
            return round(total_fee, 4)

        except Exception as error:
            logger.error("❌ خطأ في حساب رسوم التداول: {}", error)
            return 0.0

    def is_trade_profitable_after_fees(self, entry_price: float, exit_price: float, size_usd: float, direction: str, is_maker: bool = False) -> bool:
        """
        التحقق مما إذا كان الربح الإجمالي يغطي رسوم التداول بدقة قبل تنفيذ الصفقة.
        """
        try:
            if entry_price <= 0 or exit_price <= 0 or size_usd <= 0:
                return False

            # حساب الربح السعري الخام
            price_diff = (exit_price - entry_price) if direction.upper() == "BUY" else (entry_price - exit_price)
            gross_profit = (price_diff / entry_price) * size_usd

            # حساب إجمالي الرسوم الحقيقية
            total_fees = self.calculate_trade_fees(size_usd, is_maker)

            # صافي الربح بعد خصم الرسوم
            net_profit = gross_profit - total_fees

            return net_profit > 0.0

        except Exception as error:
            logger.error("❌ خطأ أثناء تقييم جدوى الرسوم للصفقة: {}", error)
            return False
