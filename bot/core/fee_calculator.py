# ======================================
# APEX TRADER - Fee Calculator
# ======================================
# حساب العمولات بدقة متناهية
# لضمان الربحية الحقيقية

from dataclasses import dataclass
from typing import Tuple
from loguru import logger
from bot.config import config


@dataclass
class FeeResult:
    """نتيجة حساب العمولات"""
    entry_fee: float        # عمولة الدخول
    exit_fee: float         # عمولة الخروج
    total_fee: float        # إجمالي العمولات
    total_fee_pct: float    # نسبة العمولة من الحجم
    breakeven_pct: float    # نسبة التعادل الحقيقية
    min_profit_pct: float   # أدنى ربح مقبول (3x العمولة)
    is_viable: bool         # هل الصفقة مجدية؟


class FeeCalculator:
    """
    حاسبة العمولات الاحترافية
    
    تحسب العمولات الحقيقية لكل صفقة
    وتحدد الأهداف الفعلية بعد الخصم
    """
    
    def __init__(self, exchange: str = "binance"):
        """
        تهيئة حاسبة العمولات
        
        Args:
            exchange: اسم المنصة (binance/bybit)
        """
        self.exchange = exchange.lower()
        self._load_fees()
    
    def _load_fees(self) -> None:
        """تحميل نسب العمولات من الإعدادات"""
        if self.exchange == "binance":
            self.maker_fee = config.risk.binance_maker_fee
            self.taker_fee = config.risk.binance_taker_fee
        elif self.exchange == "bybit":
            self.maker_fee = config.risk.bybit_maker_fee
            self.taker_fee = config.risk.bybit_taker_fee
        else:
            # افتراضي للمنصات الأخرى
            self.maker_fee = 0.001
            self.taker_fee = 0.001
    
    def calculate(
        self,
        position_size: float,
        entry_type: str = "taker",
        exit_type: str = "maker",
        leverage: int = 1
    ) -> FeeResult:
        """
        حساب العمولات الكاملة للصفقة
        
        Args:
            position_size: حجم الصفقة بالدولار (بعد الرافعة)
            entry_type: نوع أمر الدخول (maker/taker)
            exit_type: نوع أمر الخروج (maker/taker)
            leverage: الرافعة المالية
            
        Returns:
            FeeResult: نتيجة العمولات الكاملة
        """
        try:
            # حساب العمولات الفعلية
            entry_rate = (
                self.maker_fee 
                if entry_type == "maker" 
                else self.taker_fee
            )
            exit_rate = (
                self.maker_fee 
                if exit_type == "maker" 
                else self.taker_fee
            )
            
            entry_fee = position_size * entry_rate
            exit_fee = position_size * exit_rate
            total_fee = entry_fee + exit_fee
            
            # نسبة العمولة الإجمالية
            total_fee_pct = (entry_rate + exit_rate) * 100
            
            # نسبة التعادل الحقيقية
            # = الحركة المطلوبة لتغطية العمولات
            breakeven_pct = total_fee_pct
            
            # أدنى ربح مقبول = 3x العمولة
            # قاعدة: لا تدخل إذا المتوقع < 3x العمولة
            min_profit_pct = breakeven_pct * 3
            
            # هل الصفقة مجدية اقتصادياً؟
            is_viable = position_size > (total_fee * 10)
            
            result = FeeResult(
                entry_fee=round(entry_fee, 6),
                exit_fee=round(exit_fee, 6),
                total_fee=round(total_fee, 6),
                total_fee_pct=round(total_fee_pct, 4),
                breakeven_pct=round(breakeven_pct, 4),
                min_profit_pct=round(min_profit_pct, 4),
                is_viable=is_viable
            )
            
            logger.debug(
                f"💸 العمولات: دخول=${entry_fee:.4f} "
                f"خروج=${exit_fee:.4f} "
                f"إجمالي=${total_fee:.4f} "
                f"({total_fee_pct:.3f}%)"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب العمولات: {e}")
            # إرجاع قيم آمنة عند الخطأ
            return FeeResult(
                entry_fee=0,
                exit_fee=0,
                total_fee=0,
                total_fee_pct=0,
                breakeven_pct=0.1,
                min_profit_pct=0.3,
                is_viable=False
            )
    
    def adjust_targets(
        self,
        entry_price: float,
        direction: str,
        sl_pct: float,
        tp1_pct: float,
        tp2_pct: float,
        position_size: float
    ) -> dict:
        """
        تعديل أهداف الربح والخسارة بعد احتساب العمولات
        
        Args:
            entry_price: سعر الدخول
            direction: اتجاه الصفقة (long/short)
            sl_pct: نسبة وقف الخسارة
            tp1_pct: نسبة الهدف الأول
            tp2_pct: نسبة الهدف الثاني
            position_size: حجم الصفقة
            
        Returns:
            dict: الأسعار المعدلة
        """
        fees = self.calculate(position_size)
        fee_adj = fees.total_fee_pct / 100
        
        if direction.lower() == "long":
            return {
                "stop_loss": round(
                    entry_price * (1 - sl_pct / 100), 2
                ),
                "breakeven": round(
                    entry_price * (1 + fee_adj), 2
                ),
                "tp1": round(
                    entry_price * (1 + (tp1_pct + fees.total_fee_pct) / 100), 
                    2
                ),
                "tp2": round(
                    entry_price * (1 + (tp2_pct + fees.total_fee_pct) / 100),
                    2
                ),
                "trailing_start": round(
                    entry_price * (1 + (0.15 + fees.total_fee_pct) / 100),
                    2
                ),
                "fees": fees
            }
        else:  # short
            return {
                "stop_loss": round(
                    entry_price * (1 + sl_pct / 100), 2
                ),
                "breakeven": round(
                    entry_price * (1 - fee_adj), 2
                ),
                "tp1": round(
                    entry_price * (1 - (tp1_pct + fees.total_fee_pct) / 100),
                    2
                ),
                "tp2": round(
                    entry_price * (1 - (tp2_pct + fees.total_fee_pct) / 100),
                    2
                ),
                "trailing_start": round(
                    entry_price * (1 - (0.15 + fees.total_fee_pct) / 100),
                    2
                ),
                "fees": fees
            }
