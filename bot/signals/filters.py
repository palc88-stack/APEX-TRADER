# ======================================
# APEX TRADER - Signal Filters
# ======================================
# فلاتر الجودة للإشارات

import pandas as pd
from typing import Optional
from loguru import logger

from bot.config import config
from bot.signals.indicators import IndicatorResult


class SignalFilters:
    """
    فلاتر الجودة المتدرجة
    
    3 مستويات من الفلترة:
    1. سريع (< 1ms)
    2. متوسط (< 10ms)
    3. نهائي (< 50ms)
    """
    
    def quick_check(
        self, 
        df: pd.DataFrame,
        current_price: float
    ) -> bool:
        """
        فحص سريع أولي
        
        يرفض 70% من الفرص فوراً
        بدون حسابات ثقيلة
        """
        # بيانات كافية؟
        if len(df) < 50:
            return False
        
        # سعر صالح؟
        if current_price <= 0:
            return False
        
        # هل هناك حجم تداول؟
        last_volume = df['volume'].iloc[-1]
        if last_volume <= 0:
            return False
        
        # الشمعة الأخيرة طبيعية؟
        last_candle = df.iloc[-1]
        if last_candle['high'] <= last_candle['low']:
            return False
        
        return True
    
    def final_check(
        self,
        signal,  # TradeSignal
        indicators: IndicatorResult
    ) -> bool:
        """
        فحص نهائي شامل للجودة
        
        يتحقق من صحة الإشارة كاملاً
        قبل الموافقة على التنفيذ
        """
        # Spread شاذ؟ (Z-Score السعر)
        if abs(indicators.price_zscore) > 3.0:
            logger.debug(
                f"🚫 Z-Score شاذ: {indicators.price_zscore:.2f}"
            )
            return False
        
        # إشارة ضعيفة جداً؟
        if indicators.signal_strength == "weak":
            if signal.confidence < 0.65:
                return False
        
        # SL منطقي؟
        if signal.stop_loss <= 0:
            return False
        
        if signal.entry_price <= 0:
            return False
        
        # نسبة Risk/Reward مقبولة؟
        from bot.signals.signal_engine import TradeDirection
        
        if signal.direction == TradeDirection.LONG:
            risk = signal.entry_price - signal.stop_loss
            reward = signal.take_profit_1 - signal.entry_price
        else:
            risk = signal.stop_loss - signal.entry_price
            reward = signal.entry_price - signal.take_profit_1
        
        if risk <= 0:
            return False
        
        risk_reward = reward / risk
        if risk_reward < 1.0:  # R:R أدنى 1:1
            logger.debug(f"🚫 R:R ضعيف: {risk_reward:.2f}")
            return False
        
        return True
