# ======================================
# APEX TRADER - Risk Manager
# ======================================
# مدير المخاطر المركزي
# الحارس الأول لرأس المال

from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime, date
from loguru import logger

from bot.config import config
from bot.core.fee_calculator import FeeCalculator
from bot.signals.signal_engine import TradeSignal, TradingMode


@dataclass
class RiskCheckResult:
    """نتيجة فحص المخاطر"""
    approved: bool              # موافق؟
    reason: str = ""           # سبب الرفض أو القبول
    adjusted_size: float = 0.0  # الحجم المعدّل
    adjusted_leverage: int = 10  # الليفريج المعدّل
    warnings: list = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class RiskManager:
    """
    مدير المخاطر الاحترافي
    
    يتحكم في:
    - حجم الصفقات
    - الحد اليومي للخسارة
    - الليفريج
    - التنويع
    """
    
    def __init__(self):
        self.fee_calculator = FeeCalculator()
        self._daily_loss: float = 0.0
        self._daily_loss_date: Optional[date] = None
        self._open_positions: int = 0
        self._daily_trades: int = 0
        logger.info("✅ Risk Manager جاهز")
    
    @property
    def daily_loss(self) -> float:
        """الخسارة اليومية الحالية"""
        # إعادة تعيين عند يوم جديد
        today = date.today()
        if self._daily_loss_date != today:
            self._daily_loss = 0.0
            self._daily_loss_date = today
            self._daily_trades = 0
        return self._daily_loss
    
    def update_daily_loss(self, pnl: float) -> None:
        """تحديث الخسارة اليومية"""
        _ = self.daily_loss  # تأكد من التحديث
        if pnl < 0:
            self._daily_loss += abs(pnl)
        self._daily_trades += 1
        
        logger.info(
            f"📊 خسارة اليوم: ${self._daily_loss:.2f} | "
            f"صفقات: {self._daily_trades}"
        )
    
    def check_signal(
        self,
        signal: TradeSignal,
        balance: float
    ) -> RiskCheckResult:
        """
        فحص الإشارة قبل التنفيذ
        
        Args:
            signal: إشارة التداول
            balance: الرصيد المتاح
            
        Returns:
            RiskCheckResult: نتيجة الفحص
        """
        warnings = []
        
        # الفحص 1: الحد اليومي للخسارة
        daily_loss_pct = (self.daily_loss / balance * 100) if balance > 0 else 0
        
        if daily_loss_pct >= config.risk.max_daily_loss_pct:
            return RiskCheckResult(
                approved=False,
                reason=f"🚨 تم الوصول لحد الخسارة اليومية "
                       f"({daily_loss_pct:.1f}%)"
            )
        
        # تحذير عند 75% من الحد
        if daily_loss_pct >= config.risk.max_daily_loss_pct * 0.75:
            warnings.append(
                f"⚠️ اقتربنا من حد الخسارة اليومية "
                f"({daily_loss_pct:.1f}%)"
            )
        
        # الفحص 2: الحد الأدنى للرصيد
        min_balance = 10.0  # $10 حد أدنى
        if balance < min_balance:
            return RiskCheckResult(
                approved=False,
                reason=f"❌ الرصيد أقل من الحد الأدنى (${min_balance})"
            )
        
        # الفحص 3: حساب حجم الصفقة المناسب
        adjusted_size, adjusted_leverage = self._calculate_safe_size(
            signal, balance, daily_loss_pct, warnings
        )
        
        # الفحص 4: هل الصفقة مجدية بعد العمولات؟
        position_value = adjusted_size * adjusted_leverage
        fees = self.fee_calculator.calculate(position_value)
        
        if not fees.is_viable:
            return RiskCheckResult(
                approved=False,
                reason="❌ الصفقة غير مجدية بعد العمولات"
            )
        
        # الفحص 5: عدد الصفقات المفتوحة
        if self._open_positions >= 3:
            warnings.append("⚠️ 3 صفقات مفتوحة - حذر من التشتت")
        
        if self._open_positions >= 5:
            return RiskCheckResult(
                approved=False,
                reason="❌ الحد الأقصى للصفقات المفتوحة (5)"
            )
        
        return RiskCheckResult(
            approved=True,
            reason="✅ فحص المخاطر اجتاز بنجاح",
            adjusted_size=adjusted_size,
            adjusted_leverage=adjusted_leverage,
            warnings=warnings
        )
    
    def _calculate_safe_size(
        self,
        signal: TradeSignal,
        balance: float,
        daily_loss_pct: float,
        warnings: list
    ) -> Tuple[float, int]:
        """
        حساب الحجم الآمن مع Kelly Criterion المعدّل
        
        Returns:
            Tuple: (الحجم بالدولار, الليفريج)
        """
        # الحجم الأساسي
        base_size_pct = signal.position_size_pct
        
        # تقليل الحجم حسب الخسارة اليومية
        remaining_budget_pct = (
            config.risk.max_daily_loss_pct - daily_loss_pct
        ) / config.risk.max_daily_loss_pct
        
        adjusted_size_pct = base_size_pct * remaining_budget_pct
        
        # Recovery Mode: تقليل الحجم بعد خسارة
        if daily_loss_pct > config.risk.max_daily_loss_pct * 0.5:
            adjusted_size_pct *= 0.5
            warnings.append("🔄 Recovery Mode: حجم مقلل 50%")
        
        # تأكد من الحدود
        adjusted_size_pct = max(0.5, min(
            adjusted_size_pct,
            config.risk.max_position_pct
        ))
        
        # الحجم الفعلي بالدولار
        size_usd = balance * (adjusted_size_pct / 100)
        size_usd = max(1.0, size_usd)  # $1 حد أدنى
        
        # الليفريج
        leverage = min(
            signal.leverage,
            config.risk.max_leverage
        )
        
        # تقليل الليفريج في وضع الحذر
        if daily_loss_pct > config.risk.max_daily_loss_pct * 0.5:
            leverage = min(leverage, 10)
        
        return round(size_usd, 2), leverage
    
    def position_opened(self) -> None:
        """إخبار Risk Manager بفتح صفقة"""
        self._open_positions += 1
        logger.debug(f"📈 صفقات مفتوحة: {self._open_positions}")
    
    def position_closed(self, pnl: float) -> None:
        """إخبار Risk Manager بإغلاق صفقة"""
        self._open_positions = max(0, self._open_positions - 1)
        self.update_daily_loss(pnl)
        logger.debug(
            f"📉 صفقة مغلقة | P&L: ${pnl:.2f} | "
            f"مفتوحة: {self._open_positions}"
        )
    
    def get_status(self, balance: float) -> dict:
        """الحالة الكاملة لإدارة المخاطر"""
        daily_loss_pct = (
            self.daily_loss / balance * 100
        ) if balance > 0 else 0
        
        return {
            "daily_loss_usd": round(self.daily_loss, 2),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "remaining_budget_pct": round(
                max(0, config.risk.max_daily_loss_pct - daily_loss_pct), 
                2
            ),
            "open_positions": self._open_positions,
            "daily_trades": self._daily_trades,
            "status": (
                "🔴 STOPPED" 
                if daily_loss_pct >= config.risk.max_daily_loss_pct
                else "🟡 CAUTION" 
                if daily_loss_pct >= config.risk.max_daily_loss_pct * 0.75
                else "🟢 NORMAL"
            )
        }
