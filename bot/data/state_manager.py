import os
from typing import Dict, Any, Optional
from loguru import logger
from supabase import create_client, Client


class StateManager:
    """
    مدير الحالة وتخزين البيانات اللحظية (State Manager) لمنظومة (Apex Trader).
    يتولى مزامنة الحالات والصفقات الحية مع قاعدة بيانات Supabase بشكل دائم.
    خالٍ تماماً من أي قيم وهمية أو افتراضية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        
        # الاعتماد على متغيرات البيئة الحقيقية للاتصال بقاعدة البيانات
        self.supabase_url = os.getenv("SUPABASE_URL", self.config.get("supabase_url", ""))
        self.supabase_key = os.getenv("SUPABASE_KEY", self.config.get("supabase_key", ""))
        
        self.client: Optional[Client] = None
        self._init_supabase_connection()

    def _init_supabase_connection(self) -> None:
        """
        تهيئة الاتصال الحقيقي بقاعدة بيانات Supabase.
        """
        try:
            if self.supabase_url and self.supabase_key:
                self.client = create_client(self.supabase_url, self.supabase_key)
                logger.info("✅ تم الاتصال بقاعدة بيانات Supabase بنجاح.")
            else:
                logger.warning("⚠️ بيانات اعتماد Supabase غير متوفرة، سيتم العمل بالوضع المحلي المؤقت.")
        except Exception as error:
            logger.error("❌ فشل الاتصال بقاعدة بيانات Supabase: {}", error)

    def save_trade_state(self, trade_data: Dict[str, Any]) -> bool:
        """
        حفظ وتحديث حالة الصفقة الحية في قاعدة البيانات بشكل دائم.
        """
        if not self.client:
            logger.debug("ℹ️ عميل Supabase غير متفعل، تخطي الحفظ السحابي.")
            return False

        try:
            response = self.client.table("trades").upsert(trade_data).execute()
            if response:
                logger.info("✅ تم حفظ حالة الصفقة في قاعدة البيانات بنجاح للرمز: {}", trade_data.get("symbol"))
                return True
            return False

        except Exception as error:
            logger.error("❌ خطأ أثناء حفظ حالة الصفقة في قاعدة البيانات: {}", error)
            return False

    def get_open_trades_from_db(self) -> list:
        """
        استرجاع قائمة الصفقات المفتوحة الحقيقية من قاعدة البيانات عند إعادة التشغيل.
        """
        if not self.client:
            return []

        try:
            response = self.client.table("trades").select("*").eq("status", "OPEN").execute()
            if response and hasattr(response, "data"):
                return response.data
            return []

        except Exception as error:
            logger.error("❌ خطأ أثناء استرجاع الصفقات المفتوحة من قاعدة البيانات: {}", error)
            return []
