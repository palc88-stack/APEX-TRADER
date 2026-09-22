# ======================================
# APEX TRADER - Position Manager  
# ======================================
# إدارة الصفقات المفتوحة
# مع Trailing Stop ذكي

from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum
from loguru import logger

from bot.config import config
from bot.signals.signal_engine import TradeDirection


class PositionStatus(Enum):
    """حالة الصفقة"""
    OPEN = "OPEN"
    CLOSED_TP1 = "CLOSED_TP1"
    CLOSED_TP2 = "CLOSED_TP2"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_TRAILING = "CLOSED_TRAILING"
    CLOSED_MANUAL = "CLOSED_MANUAL"


@dataclass
class Position:
    """
    صفقة مفتوحة مع كامل التفاصيل
    """
    # معلومات أساسية
    id: str = ""
    symbol: str = ""
    direction: TradeDirection = TradeDirection.LONG
    exchange: str = "binance"
    
    # الأسعار
    entry_price: float = 0.0
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    
    # Trailing Stop
    trailing_active: bool = False
    trailing_stop: float = 0.0
    highest_price: float = 0.0   # أعلى سعر (للـ Long)
    lowest_price: float = 0.0    # أدنى سعر (للـ Short)
    breakeven_set: bool = False
    
    # الحجم
    size_usd: float = 0.0
    leverage: int = 10
    
    # العمولات
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    
    # التوقيت
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    
    # النتيجة
    status: PositionStatus = PositionStatus.OPEN
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # TP1 تم تنفيذه؟
    tp1_executed: bool = False
    
    @property
    def position_value(self) -> float:
        """قيمة الصفقة الإجمالية"""
        return self.size_usd * self.leverage
    
    @property
    def duration_minutes(self) -> float:
        """مدة الصفقة بالدقائق"""
        end = self.closed_at or datetime.utcnow()
        return (end - self.opened_at).total_seconds() / 60
    
    @property
    def unrealized_pnl(self) -> float:
        """الربح/الخسارة غير المحقق"""
        if not self.current_price or not self.entry_price:
            return 0.0
        
        price_change_pct = (
            (self.current_price - self.entry_price) / self.entry_price
        )
        
        if self.direction == TradeDirection.SHORT:
            price_change_pct = -price_change_pct
        
        return self.position_value * price_change_pct
    
    @property
    def unrealized_pnl_pct(self) -> float:
        """نسبة الربح/الخسارة غير المحقق"""
        if self.size_usd <= 0:
            return 0.0
        return (self.unrealized_pnl / self.size_usd) * 100


class PositionManager:
    """
    مدير الصفقات الاحترافي
    
    يتولى:
    - تتبع الصفقات المفتوحة
    - Trailing Stop ذكي
    - Break Even تلقائي
    - Partial TP
    """
    
    def __init__(self):
        self._positions: Dict[str, Position] = {}
        logger.info("✅ Position Manager جاهز")
    
    def add_position(self, position: Position) -> None:
        """إضافة صفقة جديدة"""
        self._positions[position.id] = position
        
        # تهيئة أعلى/أدنى سعر
        position.highest_price = position.entry_price
        position.lowest_price = position.entry_price
        
        logger.info(
            f"📊 صفقة جديدة: {position.symbol} "
            f"{position.direction.value} @ "
            f"{position.entry_price}"
        )
    
    def update_price(
        self, 
        position_id: str,
        current_price: float,
        atr: float = 0.0
    ) -> Optional[dict]:
        """
        تحديث السعر الحالي وإدارة Trailing Stop
        
        Args:
            position_id: معرّف الصفقة
            current_price: السعر الحالي
            atr: قيمة ATR للمسافات الديناميكية
            
        Returns:
            dict: إجراء مطلوب (close/update/none)
        """
        position = self._positions.get(position_id)
        if not position:
            return None
        
        position.current_price = current_price
        
        # تحديث أعلى/أدنى سعر
        if current_price > position.highest_price:
            position.highest_price = current_price
        if current_price < position.lowest_price:
            position.lowest_price = current_price
        
        # فحص وقف الخسارة الأصلي
        if self._check_stop_loss(position, current_price):
            return {
                "action": "close",
                "reason": "stop_loss",
                "price": current_price
            }
        
        # إدارة Trailing Stop
        trailing_action = self._manage_trailing(
            position, current_price, atr
        )
        if trailing_action:
            return trailing_action
        
        # فحص Take Profit
        tp_action = self._check_take_profit(position, current_price)
        if tp_action:
            return tp_action
        
        return {"action": "none"}
    
    def _check_stop_loss(
        self,
        position: Position,
        price: float
    ) -> bool:
        """فحص وقف الخسارة"""
        if position.direction == TradeDirection.LONG:
            # إذا الـ Trailing مفعل، استخدمه
            sl = (
                position.trailing_stop 
                if position.trailing_active 
                else position.stop_loss
            )
            return price <= sl
        else:
            sl = (
                position.trailing_stop 
                if position.trailing_active 
                else position.stop_loss
            )
            return price >= sl
    
    def _manage_trailing(
        self,
        position: Position,
        price: float,
        atr: float
    ) -> Optional[dict]:
        """
        إدارة Trailing Stop الذكي
        
        المراحل:
        1. Break Even عند 0.15% ربح
        2. Trailing يبدأ عند 0.30% ربح
        3. Trailing يتبع السعر بمسافة ATR
        """
        entry = position.entry_price
        
        # حساب الربح الحالي %
        if position.direction == TradeDirection.LONG:
            profit_pct = (price - entry) / entry * 100
        else:
            profit_pct = (entry - price) / entry * 100
        
        # المرحلة 1: Break Even
        if (not position.breakeven_set and 
                profit_pct >= config.risk.breakeven_pct):
            position.stop_loss = entry
            position.breakeven_set = True
            logger.info(
                f"🔒 Break Even مُفعَّل: {position.symbol}"
            )
        
        # المرحلة 2: تفعيل Trailing
        trailing_start = config.risk.trailing_activation_pct
        
        if profit_pct >= trailing_start and not position.trailing_active:
            position.trailing_active = True
            
            # تهيئة Trailing Stop
            trail_distance = max(
                atr / entry * 100 if atr > 0 else 0.20,
                0.15
            )
            
            if position.direction == TradeDirection.LONG:
                position.trailing_stop = price * (
                    1 - trail_distance / 100
                )
            else:
                position.trailing_stop = price * (
                    1 + trail_distance / 100
                )
            
            logger.info(
                f"🔄 Trailing مُفعَّل: {position.symbol} "
                f"@ {position.trailing_stop:.2f}"
            )
        
        # المرحلة 3: تحديث Trailing
        if position.trailing_active:
            trail_distance = max(
                atr / entry * 100 if atr > 0 else 0.20,
                0.15
            )
            
            if position.direction == TradeDirection.LONG:
                new_trail = price * (1 - trail_distance / 100)
                # Trailing يتحرك للأعلى فقط!
                if new_trail > position.trailing_stop:
                    position.trailing_stop = new_trail
                
                # فحص الـ Trailing
                if price <= position.trailing_stop:
                    return {
                        "action": "close",
                        "reason": "trailing_stop",
                        "price": price
                    }
            
            else:  # SHORT
                new_trail = price * (1 + trail_distance / 100)
                # Trailing يتحرك للأسفل فقط!
                if new_trail < position.trailing_stop:
                    position.trailing_stop = new_trail
                
                if price >= position.trailing_stop:
                    return {
                        "action": "close",
                        "reason": "trailing_stop",
                        "price": price
                    }
        
        return None
    
    def _check_take_profit(
        self,
        position: Position,
        price: float
    ) -> Optional[dict]:
        """فحص أهداف الربح مع Partial Exit"""
        
        if position.direction == TradeDirection.LONG:
            # TP1: إغلاق 50% عند الهدف الأول
            if (not position.tp1_executed and 
                    price >= position.take_profit_1):
                position.tp1_executed = True
                return {
                    "action": "partial_close",
                    "reason": "tp1",
                    "percentage": 50,
                    "price": price
                }
            
            # TP2: إغلاق البقية
            if (position.tp1_executed and 
                    price >= position.take_profit_2):
                return {
                    "action": "close",
                    "reason": "tp2",
                    "price": price
                }
        
        else:  # SHORT
            if (not position.tp1_executed and 
                    price <= position.take_profit_1):
                position.tp1_executed = True
                return {
                    "action": "partial_close",
                    "reason": "tp1",
                    "percentage": 50,
                    "price": price
                }
            
            if (position.tp1_executed and 
                    price <= position.take_profit_2):
                return {
                    "action": "close",
                    "reason": "tp2",
                    "price": price
                }
        
        return None
    
    def close_position(
        self,
        position_id: str,
        close_price: float,
        reason: str
    ) -> Optional[Position]:
        """إغلاق الصفقة وحساب النتيجة"""
        position = self._positions.get(position_id)
        if not position:
            return None
        
        position.closed_at = datetime.utcnow()
        
        # حساب P&L
        price_change = close_price - position.entry_price
        if position.direction == TradeDirection.SHORT:
            price_change = -price_change
        
        gross_pnl = (
            price_change / position.entry_price * position.position_value
        )
        net_pnl = gross_pnl - position.entry_fee - position.exit_fee
        
        position.pnl = round(net_pnl, 4)
        position.pnl_pct = round(
            (net_pnl / position.size_usd) * 100, 4
        )
        
        # تحديد حالة الإغلاق
        status_map = {
            "tp1": PositionStatus.CLOSED_TP1,
            "tp2": PositionStatus.CLOSED_TP2,
            "stop_loss": PositionStatus.CLOSED_SL,
            "trailing_stop": PositionStatus.CLOSED_TRAILING,
            "manual": PositionStatus.CLOSED_MANUAL
        }
        position.status = status_map.get(reason, PositionStatus.CLOSED_MANUAL)
        
        # إزالة من القائمة النشطة
        del self._positions[position_id]
        
        emoji = "✅" if position.pnl >= 0 else "❌"
        logger.info(
            f"{emoji} صفقة مغلقة: {position.symbol} | "
            f"سبب: {reason} | "
            f"P&L: ${position.pnl:.4f} ({position.pnl_pct:.2f}%) | "
            f"مدة: {position.duration_minutes:.1f} دقيقة"
        )
        
        return position
    
    def get_all_positions(self) -> List[Position]:
        """جميع الصفقات المفتوحة"""
        return list(self._positions.values())
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """صفقة محددة"""
        return self._positions.get(position_id)
    
    @property
    def total_unrealized_pnl(self) -> float:
        """إجمالي الربح/الخسارة غير المحقق"""
        return sum(p.unrealized_pnl for p in self._positions.values())
    
    @property
    def count(self) -> int:
        """عدد الصفقات المفتوحة"""
        return len(self._positions)
