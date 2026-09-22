# ======================================
# APEX TRADER - Signal Engine
# ======================================
# محرك الإشارات المركزي
# يجمع كل المؤشرات ويولد قرار التداول

from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum
import pandas as pd
from loguru import logger

from bot.signals.indicators import TechnicalIndicators, IndicatorResult
from bot.signals.filters import SignalFilters
from bot.config import config


class TradingMode(Enum):
    """أوضاع التداول"""
    SNIPER = "SNIPER"       # صفقات نادرة عالية الجودة
    HUNTER = "HUNTER"       # صفقات متوازنة
    FARMER = "FARMER"       # صفقات كثيرة سريعة
    EXPLOSION = "EXPLOSION"  # انفجار سعري


class TradeDirection(Enum):
    """اتجاه الصفقة"""
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass
class TradeSignal:
    """إشارة التداول الكاملة"""
    direction: TradeDirection = TradeDirection.NONE
    mode: TradingMode = TradingMode.HUNTER
    confidence: float = 0.0          # نسبة الثقة 0-1
    symbol: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    leverage: int = 10
    position_size_pct: float = 5.0   # % من المحفظة
    
    # تفاصيل الإشارة
    reasons: list = None             # أسباب الدخول
    warnings: list = None            # تحذيرات
    indicators: IndicatorResult = None
    
    # انفجار سعري؟
    is_explosion: bool = False
    explosion_score: float = 0.0
    
    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []
        if self.warnings is None:
            self.warnings = []
    
    @property
    def is_valid(self) -> bool:
        """هل الإشارة صالحة للتداول؟"""
        return (
            self.direction != TradeDirection.NONE
            and self.confidence >= 0.55
            and self.entry_price > 0
            and self.stop_loss > 0
        )
    
    def to_dict(self) -> dict:
        """تحويل لـ dictionary للحفظ"""
        return {
            "direction": self.direction.value,
            "mode": self.mode.value,
            "confidence": self.confidence,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "leverage": self.leverage,
            "position_size_pct": self.position_size_pct,
            "reasons": self.reasons,
            "is_explosion": self.is_explosion
        }


class SignalEngine:
    """
    محرك الإشارات المركزي
    
    يجمع بين:
    - المؤشرات التقنية
    - فلاتر الجودة
    - نظام التقييم
    - تحديد الوضع المناسب
    """
    
    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.filters = SignalFilters()
        logger.info("✅ Signal Engine جاهز")
    
    def analyze(
        self, 
        symbol: str,
        df: pd.DataFrame,
        current_price: float,
        orderbook: Optional[dict] = None
    ) -> TradeSignal:
        """
        التحليل الكامل لعملة واحدة
        
        Args:
            symbol: رمز العملة (BTC/USDT)
            df: بيانات الشموع التاريخية
            current_price: السعر الحالي
            orderbook: دفتر الأوامر (اختياري)
            
        Returns:
            TradeSignal: إشارة التداول الكاملة
        """
        signal = TradeSignal(symbol=symbol, entry_price=current_price)
        
        try:
            # الخطوة 1: فلاتر أولية سريعة
            if not self.filters.quick_check(df, current_price):
                logger.debug(f"⏭️ {symbol}: فشل الفحص الأولي")
                return signal
            
            # الخطوة 2: حساب المؤشرات
            indicators = self.indicators.calculate_all(df)
            if indicators is None:
                return signal
            
            signal.indicators = indicators
            
            # الخطوة 3: كشف الانفجار السعري
            explosion_score = self._detect_explosion(
                indicators, df, current_price
            )
            signal.explosion_score = explosion_score
            signal.is_explosion = explosion_score >= 0.80
            
            # الخطوة 4: تحديد الاتجاه
            direction, confidence, reasons = self._determine_direction(
                indicators, orderbook, signal.is_explosion
            )
            
            if direction == TradeDirection.NONE:
                return signal
            
            signal.direction = direction
            signal.confidence = confidence
            signal.reasons = reasons
            
            # الخطوة 5: تحديد وضع التداول
            signal.mode = self._select_mode(
                confidence, signal.is_explosion
            )
            
            # الخطوة 6: تحديد الليفريج والحجم
            signal.leverage, signal.position_size_pct = (
                self._calculate_position(signal.mode, confidence)
            )
            
            # الخطوة 7: حساب المستويات
            self._set_levels(signal, indicators)
            
            # الخطوة 8: فلاتر نهائية للجودة
            if not self.filters.final_check(signal, indicators):
                logger.debug(
                    f"⏭️ {symbol}: فشل الفحص النهائي"
                )
                return TradeSignal(symbol=symbol)
            
            if signal.is_valid:
                logger.info(
                    f"✅ إشارة {signal.direction.value} "
                    f"على {symbol} | "
                    f"ثقة: {confidence:.1%} | "
                    f"وضع: {signal.mode.value}"
                )
            
            return signal
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحليل {symbol}: {e}")
            return TradeSignal(symbol=symbol)
    
    def _detect_explosion(
        self,
        indicators: IndicatorResult,
        df: pd.DataFrame,
        current_price: float
    ) -> float:
        """
        كشف الانفجار السعري
        
        Returns:
            float: نقاط الانفجار 0-1
        """
        score = 0.0
        checks = 0
        
        # 1. BB Squeeze + كسر
        if indicators.bb_squeeze:
            if (current_price > indicators.bb_upper or 
                    current_price < indicators.bb_lower):
                score += 0.25
                checks += 1
        
        # 2. حجم مرتفع جداً
        if indicators.volume_ratio > 3.0:
            score += 0.25
            checks += 1
        elif indicators.volume_ratio > 2.0:
            score += 0.15
            checks += 1
        
        # 3. ATR مرتفع
        if indicators.atr_pct > 0.3:
            score += 0.20
            checks += 1
        
        # 4. Z-Score شاذ
        if abs(indicators.volume_zscore) > 2.5:
            score += 0.15
            checks += 1
        
        # 5. Hurst اتجاهي قوي
        if indicators.hurst > 0.65:
            score += 0.15
            checks += 1
        
        return min(score, 1.0)
    
    def _determine_direction(
        self,
        indicators: IndicatorResult,
        orderbook: Optional[dict],
        is_explosion: bool
    ) -> Tuple[TradeDirection, float, list]:
        """
        تحديد اتجاه الصفقة ومستوى الثقة
        
        Returns:
            Tuple: (الاتجاه, الثقة, الأسباب)
        """
        reasons = []
        long_score = 0.0
        short_score = 0.0
        
        trend = indicators.trend_score
        
        # === تقييم Long ===
        
        # EMA صعودي
        if indicators.ema_9 > indicators.ema_21:
            long_score += 0.20
            reasons.append("EMA صعودي")
        
        # RSI منطقة صعود
        if 40 < indicators.rsi < 65:
            long_score += 0.15
            reasons.append(f"RSI مناسب: {indicators.rsi:.1f}")
        elif indicators.rsi_signal == "oversold":
            long_score += 0.25
            reasons.append("RSI تشبع بيع")
        
        # MACD صعودي
        if indicators.macd_trend == "bullish":
            long_score += 0.20
            reasons.append("MACD صعودي")
        
        # سعر عند دعم BB
        if indicators.bb_position == "lower":
            long_score += 0.15
            reasons.append("سعر عند دعم BB")
        
        # حجم مرتفع
        if indicators.volume_trend == "high":
            if trend > 0:
                long_score += 0.10
        
        # Order Book
        if orderbook:
            ob_score = self._analyze_orderbook(orderbook)
            if ob_score > 0.6:
                long_score += 0.10
                reasons.append(f"Order Book ضغط شراء")
        
        # === تقييم Short (معكوس) ===
        if indicators.ema_9 < indicators.ema_21:
            short_score += 0.20
        if indicators.rsi_signal == "overbought":
            short_score += 0.25
        elif indicators.rsi > 60:
            short_score += 0.15
        if indicators.macd_trend == "bearish":
            short_score += 0.20
        if indicators.bb_position == "upper":
            short_score += 0.15
        if indicators.volume_trend == "high" and trend < 0:
            short_score += 0.10
        if orderbook:
            ob_score = self._analyze_orderbook(orderbook)
            if ob_score < 0.4:
                short_score += 0.10
        
        # Z-Score فلتر
        # إذا السعر شاذ جداً = خطر
        if abs(indicators.price_zscore) > 2.5:
            if indicators.price_zscore > 0:
                long_score *= 0.5    # تقليل Long إذا سعر مرتفع جداً
            else:
                short_score *= 0.5   # تقليل Short إذا سعر منخفض جداً
        
        # تحديد الاتجاه
        min_threshold = 0.55
        
        if long_score > short_score and long_score >= min_threshold:
            return TradeDirection.LONG, long_score, reasons
        elif short_score > long_score and short_score >= min_threshold:
            reasons = [
                f"RSI مرتفع: {indicators.rsi:.1f}" 
                if indicators.rsi_signal == "overbought" 
                else "EMA هبوطي"
            ]
            return TradeDirection.SHORT, short_score, reasons
        
        return TradeDirection.NONE, 0.0, []
    
    def _analyze_orderbook(self, orderbook: dict) -> float:
        """
        تحليل دفتر الأوامر
        
        Returns:
            float: 0 (ضغط بيع) إلى 1 (ضغط شراء)
        """
        try:
            bids = orderbook.get('bids', [])[:10]  # أفضل 10
            asks = orderbook.get('asks', [])[:10]
            
            if not bids or not asks:
                return 0.5
            
            bid_volume = sum(float(b[1]) for b in bids)
            ask_volume = sum(float(a[1]) for a in asks)
            
            total = bid_volume + ask_volume
            if total == 0:
                return 0.5
            
            return bid_volume / total
            
        except Exception:
            return 0.5
    
    def _select_mode(
        self, 
        confidence: float,
        is_explosion: bool
    ) -> TradingMode:
        """اختيار وضع التداول المناسب"""
        if is_explosion:
            return TradingMode.EXPLOSION
        elif confidence >= config.trading.min_confidence_sniper:
            return TradingMode.SNIPER
        elif confidence >= config.trading.min_confidence_hunter:
            return TradingMode.HUNTER
        else:
            return TradingMode.FARMER
    
    def _calculate_position(
        self, 
        mode: TradingMode,
        confidence: float
    ) -> Tuple[int, float]:
        """
        حساب الليفريج وحجم الصفقة
        
        Returns:
            Tuple: (الليفريج, % من المحفظة)
        """
        if mode == TradingMode.EXPLOSION:
            leverage = min(15, config.risk.max_leverage)
            size_pct = 15.0 * confidence
        elif mode == TradingMode.SNIPER:
            leverage = config.trading.leverage_sniper
            size_pct = 15.0 * confidence
        elif mode == TradingMode.HUNTER:
            leverage = config.trading.leverage_hunter
            size_pct = 8.0 * confidence
        else:  # FARMER
            leverage = config.trading.leverage_farmer
            size_pct = 3.0 * confidence
        
        # ضمان الحدود
        leverage = min(leverage, config.risk.max_leverage)
        size_pct = min(size_pct, config.risk.max_position_pct)
        size_pct = max(size_pct, 1.0)  # حد أدنى 1%
        
        return leverage, round(size_pct, 2)
    
    def _set_levels(
        self, 
        signal: TradeSignal,
        indicators: IndicatorResult
    ) -> None:
        """
        تحديد مستويات الدخول والخروج
        مع مراعاة ATR للمسافات الديناميكية
        """
        price = signal.entry_price
        
        # مسافة SL ديناميكية بناءً على ATR
        atr_multiplier = 1.5 if signal.is_explosion else 1.0
        sl_distance = max(
            indicators.atr * atr_multiplier / price * 100,
            config.risk.default_sl_pct
        )
        
        # TP أوسع في وضع الانفجار
        tp1_pct = (
            config.risk.tp1_pct * 3 
            if signal.is_explosion 
            else config.risk.tp1_pct
        )
        tp2_pct = (
            config.risk.tp2_pct * 3 
            if signal.is_explosion 
            else config.risk.tp2_pct
        )
        
        if signal.direction == TradeDirection.LONG:
            signal.stop_loss = round(
                price * (1 - sl_distance / 100), 6
            )
            signal.take_profit_1 = round(
                price * (1 + tp1_pct / 100), 6
            )
            signal.take_profit_2 = round(
                price * (1 + tp2_pct / 100), 6
            )
        else:  # SHORT
            signal.stop_loss = round(
                price * (1 + sl_distance / 100), 6
            )
            signal.take_profit_1 = round(
                price * (1 - tp1_pct / 100), 6
            )
            signal.take_profit_2 = round(
                price * (1 - tp2_pct / 100), 6
            )
