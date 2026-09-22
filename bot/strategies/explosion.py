# ======================================
# APEX TRADER - Explosion Detector
# ======================================
# كاشف الانفجارات السعرية
# يرصد الحركات الحادة قبل وقوعها
# بيانات حقيقية 100%

from dataclasses import dataclass
from typing import Optional, List
import pandas as pd
import numpy as np
from loguru import logger

from bot.signals.indicators import IndicatorResult
from bot.config import config


@dataclass
class ExplosionSignal:
    """
    إشارة انفجار سعري محتمل
    """
    symbol: str
    direction: str              # up / down / unknown
    score: float               # 0-1 قوة الإشارة
    confidence: float          # 0-1 الثقة

    # أسباب الكشف
    squeeze_detected: bool = False
    volume_surge: bool = False
    volatility_expansion: bool = False
    liquidation_zone_nearby: bool = False
    momentum_acceleration: bool = False

    # أهداف محتملة
    estimated_move_pct: float = 0.0
    key_level_above: float = 0.0
    key_level_below: float = 0.0

    @property
    def is_valid(self) -> bool:
        """هل الانفجار مؤكد بما يكفي؟"""
        return self.score >= 0.70 and self.confidence >= 0.65


class ExplosionDetector:
    """
    كاشف الانفجارات السعرية المتقدم

    يرصد:
    - BB Squeeze + كسر
    - ارتفاع مفاجئ في الحجم
    - تسارع الزخم
    - مناطق التصفية القريبة
    - نقاط السيولة الكبيرة
    """

    # حدود الكشف
    VOLUME_SURGE_THRESHOLD = 3.0     # 3x المعدل
    BB_SQUEEZE_RATIO = 0.70          # 70% من المعدل
    MOMENTUM_THRESHOLD = 0.003       # 0.3% حركة سريعة
    MIN_SCORE_FOR_SIGNAL = 0.60

    def detect(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: IndicatorResult,
        current_price: float
    ) -> Optional[ExplosionSignal]:
        """
        الكشف الكامل عن الانفجار المحتمل

        Args:
            symbol: رمز العملة
            df: بيانات الشموع الحقيقية
            indicators: المؤشرات المحسوبة
            current_price: السعر الحالي الحقيقي

        Returns:
            ExplosionSignal أو None
        """
        try:
            signal = ExplosionSignal(
                symbol=symbol,
                direction="unknown",
                score=0.0,
                confidence=0.0
            )

            # فحوصات الانفجار
            self._check_bb_squeeze(
                df, indicators, current_price, signal
            )
            self._check_volume_surge(df, indicators, signal)
            self._check_momentum(df, current_price, signal)
            self._check_volatility_expansion(indicators, signal)
            self._estimate_targets(
                df, current_price, indicators, signal
            )

            # حساب النقاط الكلية
            score = self._calculate_score(signal)
            signal.score = score
            signal.confidence = self._calculate_confidence(
                signal, indicators
            )

            if signal.score < self.MIN_SCORE_FOR_SIGNAL:
                return None

            # تحديد الاتجاه
            signal.direction = self._determine_direction(
                df, indicators, current_price
            )

            logger.info(
                f"💥 انفجار محتمل: {symbol} | "
                f"نقاط: {score:.2f} | "
                f"اتجاه: {signal.direction} | "
                f"حركة متوقعة: {signal.estimated_move_pct:.2f}%"
            )

            return signal

        except Exception as e:
            logger.error(
                f"❌ خطأ كشف انفجار {symbol}: {e}"
            )
            return None

    def _check_bb_squeeze(
        self,
        df: pd.DataFrame,
        indicators: IndicatorResult,
        current_price: float,
        signal: ExplosionSignal
    ) -> None:
        """
        فحص BB Squeeze + كسر النطاق

        BB Squeeze = النطاق ضيق جداً
        ثم السعر يكسر النطاق = انفجار
        """
        if indicators.bb_squeeze:
            # هل كسر السعر النطاق؟
            if current_price > indicators.bb_upper:
                signal.squeeze_detected = True
                signal.direction = "up"
                logger.debug(
                    f"🔔 {signal.symbol}: BB Squeeze كسر للأعلى"
                )
            elif current_price < indicators.bb_lower:
                signal.squeeze_detected = True
                signal.direction = "down"
                logger.debug(
                    f"🔔 {signal.symbol}: BB Squeeze كسر للأسفل"
                )
            else:
                # الضغط موجود لكن لم يكسر بعد
                # انفجار قريب جداً!
                signal.squeeze_detected = True

    def _check_volume_surge(
        self,
        df: pd.DataFrame,
        indicators: IndicatorResult,
        signal: ExplosionSignal
    ) -> None:
        """
        فحص ارتفاع الحجم المفاجئ

        حجم > 3x المعدل = نشاط غير عادي
        """
        if indicators.volume_ratio >= self.VOLUME_SURGE_THRESHOLD:
            signal.volume_surge = True

            logger.debug(
                f"🔔 {signal.symbol}: "
                f"حجم x{indicators.volume_ratio:.1f}"
            )

        # فحص اتجاه الحجم
        if len(df) >= 3:
            recent_volumes = df['volume'].tail(3).values
            if (recent_volumes[-1] > recent_volumes[-2] >
                    recent_volumes[-3]):
                # حجم يتزايد = تسارع
                signal.volume_surge = True

    def _check_momentum(
        self,
        df: pd.DataFrame,
        current_price: float,
        signal: ExplosionSignal
    ) -> None:
        """
        فحص تسارع الزخم

        تحرك سريع في آخر 3 شموع = زخم قوي
        """
        if len(df) < 4:
            return

        # التغير في آخر 3 شموع
        prices = df['close'].tail(4).values
        changes = [
            abs(prices[i] - prices[i-1]) / prices[i-1]
            for i in range(1, 4)
        ]

        avg_change = sum(changes) / len(changes)

        if avg_change >= self.MOMENTUM_THRESHOLD:
            signal.momentum_acceleration = True

            # اتجاه الزخم
            net_change = (prices[-1] - prices[0]) / prices[0]
            if net_change > 0:
                signal.direction = "up"
            elif net_change < 0:
                signal.direction = "down"

            logger.debug(
                f"🔔 {signal.symbol}: "
                f"زخم {avg_change:.4f}"
            )

    def _check_volatility_expansion(
        self,
        indicators: IndicatorResult,
        signal: ExplosionSignal
    ) -> None:
        """
        فحص توسع التقلب

        ATR مرتفع = تقلب متزايد = انفجار قريب
        """
        # ATR% فوق 0.3% يشير لتقلب عالٍ
        if indicators.atr_pct >= 0.30:
            signal.volatility_expansion = True
            logger.debug(
                f"🔔 {signal.symbol}: "
                f"تقلب {indicators.atr_pct:.3f}%"
            )

    def _estimate_targets(
        self,
        df: pd.DataFrame,
        current_price: float,
        indicators: IndicatorResult,
        signal: ExplosionSignal
    ) -> None:
        """
        تقدير أهداف الحركة المتوقعة
        بناءً على بيانات حقيقية
        """
        # تقدير حجم الحركة من ATR
        estimated_move = indicators.atr_pct * 3
        signal.estimated_move_pct = round(estimated_move, 3)

        # أعلى مستوى في آخر 20 شمعة
        if len(df) >= 20:
            recent_high = float(df['high'].tail(20).max())
            recent_low = float(df['low'].tail(20).min())

            signal.key_level_above = round(recent_high, 2)
            signal.key_level_below = round(recent_low, 2)

    def _calculate_score(
        self,
        signal: ExplosionSignal
    ) -> float:
        """
        حساب نقاط قوة الانفجار
        """
        score = 0.0

        if signal.squeeze_detected:
            score += 0.30    # أهم إشارة

        if signal.volume_surge:
            score += 0.25    # ثاني أهم

        if signal.momentum_acceleration:
            score += 0.25    # ثالث

        if signal.volatility_expansion:
            score += 0.20    # رابع

        return min(score, 1.0)

    def _calculate_confidence(
        self,
        signal: ExplosionSignal,
        indicators: IndicatorResult
    ) -> float:
        """
        حساب الثقة في الإشارة
        عدد الإشارات المتوافقة
        """
        signals_count = sum([
            signal.squeeze_detected,
            signal.volume_surge,
            signal.momentum_acceleration,
            signal.volatility_expansion
        ])

        base_confidence = signals_count / 4

        # مكافأة إذا الاتجاه محدد
        if signal.direction != "unknown":
            base_confidence += 0.10

        # مكافأة Hurst اتجاهي
        if indicators.market_type == "trending":
            base_confidence += 0.10

        return min(base_confidence, 1.0)

    def _determine_direction(
        self,
        df: pd.DataFrame,
        indicators: IndicatorResult,
        current_price: float
    ) -> str:
        """
        تحديد اتجاه الانفجار المتوقع
        """
        bullish_signals = 0
        bearish_signals = 0

        # EMA
        if indicators.ema_9 > indicators.ema_21:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # MACD
        if indicators.macd_trend == "bullish":
            bullish_signals += 1
        elif indicators.macd_trend == "bearish":
            bearish_signals += 1

        # RSI
        if indicators.rsi > 50:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # موقع السعر من BB
        if indicators.bb_position == "upper":
            bullish_signals += 1
        elif indicators.bb_position == "lower":
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            return "up"
        elif bearish_signals > bullish_signals:
            return "down"
        else:
            return "unknown"
