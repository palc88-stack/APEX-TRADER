# ======================================
# APEX TRADER - Technical Indicators
# ======================================
# حساب المؤشرات التقنية بدقة عالية
# مع دعم كامل للسكالبينق

import numpy as np
import pandas as pd
from typing import Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class IndicatorResult:
    """نتائج المؤشرات التقنية"""
    # EMA
    ema_9: float = 0.0
    ema_21: float = 0.0
    ema_50: float = 0.0
    
    # RSI
    rsi: float = 50.0
    rsi_signal: str = "neutral"   # oversold/overbought/neutral
    
    # MACD
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    macd_trend: str = "neutral"
    
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_position: str = "middle"   # upper/lower/middle
    bb_squeeze: bool = False      # ضغط البولينجر
    
    # ATR - قياس التقلب
    atr: float = 0.0
    atr_pct: float = 0.0
    
    # Volume
    volume_ratio: float = 1.0    # نسبة الحجم للمعدل
    volume_trend: str = "normal"  # high/low/normal
    
    # Z-Score
    price_zscore: float = 0.0
    volume_zscore: float = 0.0
    
    # Hurst Exponent
    hurst: float = 0.5
    market_type: str = "random"  # trending/reverting/random
    
    # إشارة إجمالية
    trend_score: float = 0.0     # -1 إلى +1
    signal_strength: str = "weak"  # strong/moderate/weak


class TechnicalIndicators:
    """
    محرك المؤشرات التقنية الاحترافي
    
    يحسب جميع المؤشرات المطلوبة
    للسكالبينق الاحترافي
    """
    
    # إعدادات المؤشرات
    EMA_FAST = 9
    EMA_MEDIUM = 21
    EMA_SLOW = 50
    RSI_PERIOD = 14
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    BB_PERIOD = 20
    BB_STD = 2.0
    ATR_PERIOD = 14
    VOLUME_PERIOD = 20
    ZSCORE_PERIOD = 20
    
    def calculate_all(
        self, 
        df: pd.DataFrame
    ) -> Optional[IndicatorResult]:
        """
        حساب جميع المؤشرات دفعة واحدة
        
        Args:
            df: DataFrame يحتوي على OHLCV
                الأعمدة: open, high, low, close, volume
                
        Returns:
            IndicatorResult أو None عند الخطأ
        """
        try:
            # التحقق من كفاية البيانات
            if len(df) < self.EMA_SLOW + 10:
                logger.warning(
                    f"⚠️ بيانات غير كافية: {len(df)} شمعة"
                )
                return None
            
            result = IndicatorResult()
            
            # حساب المؤشرات
            self._calc_ema(df, result)
            self._calc_rsi(df, result)
            self._calc_macd(df, result)
            self._calc_bollinger(df, result)
            self._calc_atr(df, result)
            self._calc_volume(df, result)
            self._calc_zscore(df, result)
            self._calc_hurst(df, result)
            
            # حساب الإشارة الإجمالية
            self._calc_trend_score(result)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب المؤشرات: {e}")
            return None
    
    def _calc_ema(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """حساب المتوسطات المتحركة الأسية"""
        close = df['close']
        
        result.ema_9 = float(
            close.ewm(span=self.EMA_FAST, adjust=False).mean().iloc[-1]
        )
        result.ema_21 = float(
            close.ewm(span=self.EMA_MEDIUM, adjust=False).mean().iloc[-1]
        )
        result.ema_50 = float(
            close.ewm(span=self.EMA_SLOW, adjust=False).mean().iloc[-1]
        )
    
    def _calc_rsi(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """حساب مؤشر القوة النسبية RSI"""
        close = df['close']
        delta = close.diff()
        
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        
        avg_gain = gain.ewm(
            com=self.RSI_PERIOD - 1, 
            adjust=False
        ).mean()
        avg_loss = loss.ewm(
            com=self.RSI_PERIOD - 1, 
            adjust=False
        ).mean()
        
        # تجنب القسمة على صفر
        rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
        rsi = 100 - (100 / (1 + rs))
        
        result.rsi = float(rsi.iloc[-1])
        
        # تحديد الإشارة
        if result.rsi < 30:
            result.rsi_signal = "oversold"    # تشبع بيع = فرصة شراء
        elif result.rsi > 70:
            result.rsi_signal = "overbought"  # تشبع شراء = فرصة بيع
        else:
            result.rsi_signal = "neutral"
    
    def _calc_macd(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """حساب مؤشر MACD"""
        close = df['close']
        
        ema_fast = close.ewm(
            span=self.MACD_FAST, 
            adjust=False
        ).mean()
        ema_slow = close.ewm(
            span=self.MACD_SLOW, 
            adjust=False
        ).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(
            span=self.MACD_SIGNAL, 
            adjust=False
        ).mean()
        histogram = macd_line - signal_line
        
        result.macd = float(macd_line.iloc[-1])
        result.macd_signal = float(signal_line.iloc[-1])
        result.macd_histogram = float(histogram.iloc[-1])
        
        # اتجاه MACD
        if result.macd > result.macd_signal and result.macd_histogram > 0:
            result.macd_trend = "bullish"
        elif result.macd < result.macd_signal and result.macd_histogram < 0:
            result.macd_trend = "bearish"
        else:
            result.macd_trend = "neutral"
    
    def _calc_bollinger(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """حساب نطاقات بولينجر"""
        close = df['close']
        
        middle = close.rolling(window=self.BB_PERIOD).mean()
        std = close.rolling(window=self.BB_PERIOD).std()
        
        upper = middle + (std * self.BB_STD)
        lower = middle - (std * self.BB_STD)
        
        current_price = float(close.iloc[-1])
        result.bb_upper = float(upper.iloc[-1])
        result.bb_middle = float(middle.iloc[-1])
        result.bb_lower = float(lower.iloc[-1])
        
        # موقع السعر في النطاق
        if current_price >= result.bb_upper * 0.99:
            result.bb_position = "upper"
        elif current_price <= result.bb_lower * 1.01:
            result.bb_position = "lower"
        else:
            result.bb_position = "middle"
        
        # كشف ضغط البولينجر (Squeeze)
        # عندما تضيق النطاقات = انفجار قريب
        bb_width = (result.bb_upper - result.bb_lower) / result.bb_middle
        avg_width = float(
            ((upper - lower) / middle)
            .rolling(window=50)
            .mean()
            .iloc[-1]
        )
        
        result.bb_squeeze = bool(bb_width < avg_width * 0.7)
    
    def _calc_atr(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """حساب Average True Range للتقلب"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(
            com=self.ATR_PERIOD - 1, 
            adjust=False
        ).mean()
        
        result.atr = float(atr.iloc[-1])
        result.atr_pct = float(
            (result.atr / float(close.iloc[-1])) * 100
        )
    
    def _calc_volume(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """تحليل حجم التداول"""
        volume = df['volume']
        
        avg_volume = float(
            volume.rolling(window=self.VOLUME_PERIOD).mean().iloc[-1]
        )
        current_volume = float(volume.iloc[-1])
        
        # نسبة الحجم الحالي للمعدل
        result.volume_ratio = (
            current_volume / avg_volume 
            if avg_volume > 0 else 1.0
        )
        
        # تصنيف الحجم
        if result.volume_ratio > 2.0:
            result.volume_trend = "high"      # حجم مرتفع جداً
        elif result.volume_ratio < 0.5:
            result.volume_trend = "low"       # حجم منخفض
        else:
            result.volume_trend = "normal"
    
    def _calc_zscore(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """حساب Z-Score للسعر والحجم"""
        close = df['close']
        volume = df['volume']
        
        # Z-Score السعر
        price_mean = close.rolling(
            window=self.ZSCORE_PERIOD
        ).mean().iloc[-1]
        price_std = close.rolling(
            window=self.ZSCORE_PERIOD
        ).std().iloc[-1]
        
        if price_std > 0:
            result.price_zscore = float(
                (close.iloc[-1] - price_mean) / price_std
            )
        else:
            result.price_zscore = 0.0
        
        # Z-Score الحجم
        vol_mean = volume.rolling(
            window=self.ZSCORE_PERIOD
        ).mean().iloc[-1]
        vol_std = volume.rolling(
            window=self.ZSCORE_PERIOD
        ).std().iloc[-1]
        
        if vol_std > 0:
            result.volume_zscore = float(
                (volume.iloc[-1] - vol_mean) / vol_std
            )
        else:
            result.volume_zscore = 0.0
    
    def _calc_hurst(
        self, 
        df: pd.DataFrame, 
        result: IndicatorResult
    ) -> None:
        """
        حساب Hurst Exponent
        يحدد طبيعة السوق: اتجاهي أم عكسي أم عشوائي
        """
        try:
            close = df['close'].values[-100:]  # آخر 100 شمعة
            
            if len(close) < 20:
                result.hurst = 0.5
                result.market_type = "random"
                return
            
            lags = range(2, 20)
            tau = [
                np.sqrt(np.std(
                    np.subtract(close[lag:], close[:-lag])
                ))
                for lag in lags
            ]
            
            # Hurst = ميل المنحنى اللوغاريتمي
            poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
            hurst = poly[0]
            
            result.hurst = float(np.clip(hurst, 0, 1))
            
            # تصنيف السوق
            if result.hurst > 0.55:
                result.market_type = "trending"   # اتجاهي
            elif result.hurst < 0.45:
                result.market_type = "reverting"  # عكسي
            else:
                result.market_type = "random"     # عشوائي
                
        except Exception:
            result.hurst = 0.5
            result.market_type = "random"
    
    def _calc_trend_score(
        self, 
        result: IndicatorResult
    ) -> None:
        """
        حساب نقاط الاتجاه الإجمالية
        من -1 (هبوطي قوي) إلى +1 (صعودي قوي)
        """
        score = 0.0
        
        # EMA Score (وزن 30%)
        if result.ema_9 > result.ema_21 > result.ema_50:
            score += 0.30    # صعودي قوي
        elif result.ema_9 < result.ema_21 < result.ema_50:
            score -= 0.30    # هبوطي قوي
        elif result.ema_9 > result.ema_21:
            score += 0.15    # صعودي معتدل
        elif result.ema_9 < result.ema_21:
            score -= 0.15    # هبوطي معتدل
        
        # RSI Score (وزن 20%)
        if 40 < result.rsi < 60:
            score += 0.0     # محايد
        elif result.rsi_signal == "oversold":
            score += 0.20    # فرصة شراء
        elif result.rsi_signal == "overbought":
            score -= 0.20    # فرصة بيع
        elif result.rsi > 50:
            score += 0.10
        else:
            score -= 0.10
        
        # MACD Score (وزن 20%)
        if result.macd_trend == "bullish":
            score += 0.20
        elif result.macd_trend == "bearish":
            score -= 0.20
        
        # Volume Score (وزن 15%)
        if result.volume_trend == "high" and result.macd_histogram > 0:
            score += 0.15    # حجم مرتفع مع صعود
        elif result.volume_trend == "high" and result.macd_histogram < 0:
            score -= 0.15    # حجم مرتفع مع هبوط
        
        # BB Score (وزن 15%)
        if result.bb_position == "lower":
            score += 0.15    # سعر عند الدعم
        elif result.bb_position == "upper":
            score -= 0.15    # سعر عند المقاومة
        
        result.trend_score = float(np.clip(score, -1, 1))
        
        # تحديد قوة الإشارة
        abs_score = abs(result.trend_score)
        if abs_score >= 0.7:
            result.signal_strength = "strong"
        elif abs_score >= 0.4:
            result.signal_strength = "moderate"
        else:
            result.signal_strength = "weak"
