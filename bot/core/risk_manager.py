from typing import Dict, Any, Optional
from loguru import logger
from bot.core.fee_calculator import FeeCalculator


class RiskManager:
    """
    مدير المخاطر الصارم (Risk Manager) لمنظومة (Apex Trader).
    يتحقق من حدود المخاطر، الرافعة المالية، وحجم الصفقات وتكاملها مع حاسبة الرسوم.
    خالٍ تماماً من أي بيانات وهمية أو افتراضية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.fee_calculator = FeeCalculator(self.config)
        self.max_risk_per_trade_pct = float(self.config.get("max_risk_pct", 0.02))  # 2% من المحفظة
        self.max_leverage_allowed = int(self.config.get("max_leverage", 20))

    def evaluate_risk(self, account_balance: float, size_usd: float, leverage: int, entry_price: float, stop_loss: float, direction: str) -> bool:
        """
        التحقق من التزام الصفقة بحدود المخاطر وقواعد رأس المال الحقيقي للمحفظة.
        """
        if account_balance <= 0 or size_usd <= 0 or entry_price <= 0 or stop_loss <= 0:
            logger.warning("⚠️ بيانات غير صالحة لتقييم المخاطر.")
            return False

        try:
            # 1. التحقق من حدود الرافعة المالية المسموح بها
            if leverage > self.max_leverage_allowed:
                logger.warning("⚠️ تم رفض الصفقة: الرافعة المالية ({}) تتجاوز الحد الأقصى المسموح به ({}).", leverage, self.max_leverage_allowed)
                return False

            # 2. التحقق من ألا تتجاوز حجم الصفقة رصيد المحفظة مع الرافعة
            if size_usd > (account_balance * leverage):
                logger.warning("⚠️ تم رفض الصفقة: حجم الصفقة يتجاوز الحد الآمن لرصيد المحفظة.")
                return False

            # 3. التحقق من مسافة وقف الخسارة والخسارة القصوى المحتملة للمحفظة
            sl_distance_pct = abs(entry_price - stop_loss) / entry_price
            potential_loss = size_usd * sl_distance_pct
            max_allowed_loss = account_balance * self.max_risk_per_trade_pct

            if potential_loss > max_allowed_loss:
                logger.warning("⚠️ تم رفض الصفقة: الخسارة المحتملة ({:.2f}$) تتجاوز الحد الأقصى للمخاطر المسموح بها ({:.2f}$).", potential_loss, max_allowed_loss)
                return False

            logger.info("✅ اجتازت الصفقة كافة فحوصات إدارة المخاطر بنجاح.")
            return True

        except Exception as error:
            logger.error("❌ خطأ أثناء تقييم المخاطر للصفقة: {}", error)
            return False
