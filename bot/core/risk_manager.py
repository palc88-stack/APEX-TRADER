# bot/core/risk_manager.py - الكود المُصحَّح
from typing import Dict, Any, Optional, List, Union
from loguru import logger
from bot.core.fee_calculator import FeeCalculator


class RiskManager:
    def __init__(self, config: Optional[Union[Dict[str, Any], "Config"]] = None):
        self.config = config or {}
        self.fee_calculator = FeeCalculator(self.config)
        # قراءة قيم المخاطر — تدعم كل من dict و Config object
        if isinstance(self.config, dict):
            self.max_risk_per_trade_pct = float(
                self.config.get("max_risk_pct", 0.02)
            )
            self.max_leverage_allowed = int(
                self.config.get("max_leverage", 20)
            )
        else:
            # Config object — يقرأ من الـ nested RiskConfig
            risk_cfg = getattr(self.config, "risk", None)
            if risk_cfg is not None:
                self.max_risk_per_trade_pct = float(
                    getattr(risk_cfg, "max_daily_loss_pct", 0.02)
                )
                self.max_leverage_allowed = int(
                    getattr(risk_cfg, "max_leverage", 20)
                )
            else:
                # يَسقط إلى config.get() إذا كان Config يملكها
                self.max_risk_per_trade_pct = float(
                    getattr(self.config, "get", lambda k, d: d)(
                        "max_risk_pct", 0.02
                    )
                )
                self.max_leverage_allowed = int(
                    getattr(self.config, "get", lambda k, d: d)(
                        "max_leverage", 20
                    )
                )

    def check_risk_limits(
        self,
        signal,
        open_positions: Optional[List[dict]] = None
    ) -> bool:
        """
        ✅ الدالة المفقودة - يُستدعى من main.py
        يتحقق من:
        1. عدم وجود صفقة مفتوحة على نفس الرمز
        2. عدم تعارض الاتجاه مع صفقة مفتوحة
        3. حد الرافعة
        """
        try:
            # 1. فحص المراكز المفتوحة على نفس الرمز
            if open_positions:
                for pos in open_positions:
                    if pos.get("symbol") == signal.symbol:
                        # ❌ إذا كان الاتجاه عكسياً — رفض فوري
                        pos_dir = pos.get("direction", "").upper()
                        sig_action = str(signal.action).upper()
                        if (
                            (pos_dir == "LONG" and sig_action in ("SHORT", "SELL"))
                            or (pos_dir == "SHORT" and sig_action in ("LONG", "BUY"))
                        ):
                            logger.warning(
                                "⚠️ رُفضت الإشارة: يوجد مركز {} مفتوح على {}",
                                pos_dir, signal.symbol
                            )
                            return False
                        # ❌ إذا كان نفس الاتجاه — تجنب التضاعف
                        logger.warning(
                            "⚠️ رُفضت الإشارة: مركز مفتوح بالفعل على {}",
                            signal.symbol
                        )
                        return False

            # 2. فحص مستوى الثقة
            confidence = getattr(signal, "confidence", 0.0)
            if confidence < 0.65:
                logger.warning(
                    "⚠️ رُفضت الإشارة: الثقة منخفضة ({:.0%}) < 65%",
                    confidence
                )
                return False

            logger.info(
                "✅ اجتازت الإشارة فحوصات إدارة المخاطر: {} {}",
                signal.symbol, signal.action
            )
            return True

        except Exception as error:
            logger.error("❌ خطأ في check_risk_limits: {}", error)
            return False

    def evaluate_risk(
        self,
        account_balance: float,
        size_usd: float,
        leverage: int,
        entry_price: float,
        stop_loss: float,
        direction: str
    ) -> bool:
        """فحص تفصيلي لمعاملات الصفقة قبل تنفيذها."""
        if account_balance <= 0 or size_usd <= 0 or entry_price <= 0 or stop_loss <= 0:
            logger.warning("⚠️ بيانات غير صالحة لتقييم المخاطر.")
            return False
        try:
            if leverage > self.max_leverage_allowed:
                logger.warning(
                    "⚠️ الرافعة ({}) تتجاوز الحد ({}).",
                    leverage, self.max_leverage_allowed
                )
                return False

            if size_usd > (account_balance * leverage):
                logger.warning("⚠️ حجم الصفقة يتجاوز الحد الآمن.")
                return False

            sl_distance_pct = abs(entry_price - stop_loss) / entry_price
            potential_loss = size_usd * sl_distance_pct
            max_allowed_loss = account_balance * self.max_risk_per_trade_pct

            if potential_loss > max_allowed_loss:
                logger.warning(
                    "⚠️ الخسارة المحتملة ({:.2f}$) > الحد الأقصى ({:.2f}$).",
                    potential_loss, max_allowed_loss
                )
                return False

            logger.info("✅ اجتازت الصفقة كافة فحوصات المخاطر.")
            return True
        except Exception as error:
            logger.error("❌ خطأ في evaluate_risk: {}", error)
            return False
