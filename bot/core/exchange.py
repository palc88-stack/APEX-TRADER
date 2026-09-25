import os
from typing import Dict, Any, Optional
from loguru import logger
import ccxt


class ExchangeManager:
    """
    مدير منصات التداول (Exchange Manager) لمنظومة (Apex Trader).
    يتعامل حصرياً مع منصات التداول الحقيقية (Binance Live / Testnet) عبر مكتبة CCXT.
    خالٍ تماماً من أي بيانات وهمية أو افتراضية (Zero Mock Data).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        
        # استرجاع مفاتيح الـ API الحقيقية من بيئة النظام أو ملف الإعدادات
        self.api_key = os.getenv("BINANCE_API_KEY", self.config.get("binance_api_key", ""))
        self.secret_key = os.getenv("BINANCE_SECRET_KEY", self.config.get("binance_secret_key", ""))
        
        # التقاط قيمة وضع التست نت بدقة وتحويلها إلى قيمة منطقية (Boolean)
        testnet_env = os.getenv("BINANCE_TESTNET", str(self.config.get("binance_testnet", "false")))
        self.is_testnet = str(testnet_env).lower() in ("true", "1", "t", "yes", "on")

        self.exchange: Optional[ccxt.binance] = None
        self._init_exchange()

    def _init_exchange(self) -> None:
        """
        تهيئة الاتصال الحقيقي بمنصة بينانس عبر CCXT مع دعم التست نت واللايف.
        """
        try:
            exchange_config = {
                'apiKey': self.api_key,
                'secret': self.secret_key,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',  # يمكن تعديلها إلى future حسب إعداداتك
                }
            }

            # إنشاء كائن المنصة الحقيقي عبر CCXT
            self.exchange = ccxt.binance(exchange_config)

            # تفعيل وضع التست نت (Testnet / Sandbox) أو الحقيقي بناءً على إعداداتك
            if self.is_testnet:
                # تفعيل وضع الساندبوكس التجريبي الرسمي لمنصة بينانس
                self.exchange.set_sandbox_mode(True)
                logger.info("🧪 تم ضبط الاتصال بنجاح على وضع بينانس التجريبي الرسمي (Binance Testnet).")
            else:
                logger.info("🚀 تم ضبط الاتصال بنجاح على وضع التداول الحقيقي المباشر (Binance Live).")

        except Exception as error:
            logger.error("❌ فشل تهيئة الاتصال بمنصة بينانس الحقيقية: {}", error)

    def get_exchange_instance(self) -> Optional[ccxt.binance]:
        """
        إرجاع مثيل المنصة الفعلي للاستخدام في جلب الشموع والبيانات الحية.
        """
        if not self.exchange:
            logger.warning("⚠️ محاولة الوصول لمثيل المنصة بينما لم يتم تهيئته بنجاح.")
        return self.exchange
