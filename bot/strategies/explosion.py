from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
from loguru import logger


@dataclass
class ExplosionSignal:
    """
    إشارة انفجار سعري محتمل.
    """

    symbol: str
    direction: str
    score: float
    confidence: float

    squeeze_detected: bool = False
    volume_surge: bool = False
    volatility_expansion: bool = False
    liquidation_zone_nearby: bool = False
    momentum_acceleration: bool = False

    estimated_move_pct: float = 0.0
    key_level_above: float = 0.0
    key_level_below: float = 0.0

    @property
    def is_valid(self) -> bool:
        return (
            self.score >= 0.70
            and self.confidence >= 0.65
        )


class ExplosionDetector:
    """
    كاشف الحركات السعرية الحادة.

    يعتمد على:
    - Bollinger Band squeeze
    - ارتفاع حجم التداول
    - تسارع الزخم
    - توسع التقلب
    """

    VOLUME_SURGE_THRESHOLD = 3.0
    BB_SQUEEZE_RATIO = 0.70
    MOMENTUM_THRESHOLD = 0.003
    MIN_SCORE_FOR_SIGNAL = 0.60

    def detect(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Any,
        current_price: float,
    ) -> Optional[ExplosionSignal]:
        """
        اكتشاف انفجار سعري محتمل.

        يستخدم Any لنوع indicators لأن المشروع لا يحتوي
        على IndicatorResult فعلي. يجب أن يحتوي الكائن الممرر
        على الخصائص التي تستخدمها الدوال أدناه.
        """
        try:
            if df is None or df.empty:
                return None

            signal = ExplosionSignal(
                symbol=symbol,
                direction="unknown",
                score=0.0,
                confidence=0.0,
            )

            self._check_bb_squeeze(
                df,
                indicators,
                current_price,
                signal,
            )

            self._check_volume_surge(
                df,
                indicators,
                signal,
            )

            self._check_momentum(
                df,
                current_price,
                signal,
            )

            self._check_volatility_expansion(
                indicators,
                signal,
            )

            self._estimate_targets(
                df,
                current_price,
                indicators,
                signal,
            )

            signal.score = self._calculate_score(signal)

            signal.confidence = self._calculate_confidence(
                signal,
                indicators,
            )

            if signal.score < self.MIN_SCORE_FOR_SIGNAL:
                return None

            signal.direction = self._determine_direction(
                df,
                indicators,
                current_price,
            )

            logger.info(
                "💥 انفجار محتمل: {} | النقاط: {:.2f} | "
                "الاتجاه: {} | الحركة المتوقعة: {:.2f}%",
                symbol,
                signal.score,
                signal.direction,
                signal.estimated_move_pct,
            )

            return signal

        except Exception as error:
            logger.error(
                "❌ خطأ في كشف الانفجار للرمز {}: {}",
                symbol,
                error,
            )
            return None

    def _check_bb_squeeze(
        self,
        df: pd.DataFrame,
        indicators: Any,
        current_price: float,
        signal: ExplosionSignal,
    ) -> None:
        """
        فحص Bollinger Band squeeze وكسر النطاق.
        """
        if not getattr(indicators, "bb_squeeze", False):
            return

        bb_upper = getattr(
            indicators,
            "bb_upper",
            current_price,
        )

        bb_lower = getattr(
            indicators,
            "bb_lower",
            current_price,
        )

        if current_price > bb_upper:
            signal.squeeze_detected = True
            signal.direction = "up"

            logger.debug(
                "🔔 {}: كسر Bollinger Band للأعلى",
                signal.symbol,
            )

        elif current_price < bb_lower:
            signal.squeeze_detected = True
            signal.direction = "down"

            logger.debug(
                "🔔 {}: كسر Bollinger Band للأسفل",
                signal.symbol,
            )

        else:
            signal.squeeze_detected = True

    def _check_volume_surge(
        self,
        df: pd.DataFrame,
        indicators: Any,
        signal: ExplosionSignal,
    ) -> None:
        """
        فحص ارتفاع حجم التداول.
        """
        volume_ratio = float(
            getattr(indicators, "volume_ratio", 0.0)
        )

        if volume_ratio >= self.VOLUME_SURGE_THRESHOLD:
            signal.volume_surge = True

            logger.debug(
                "🔔 {}: ارتفاع الحجم إلى {:.1f}x",
                signal.symbol,
                volume_ratio,
            )

        if (
            "volume" in df.columns
            and len(df) >= 3
        ):
            recent_volumes = df["volume"].tail(3).values

            if (
                recent_volumes[-1] > recent_volumes[-2]
                and recent_volumes[-2] > recent_volumes[-3]
            ):
                signal.volume_surge = True

    def _check_momentum(
        self,
        df: pd.DataFrame,
        current_price: float,
        signal: ExplosionSignal,
    ) -> None:
        """
        فحص تسارع الزخم في آخر الشموع.
        """
        if (
            "close" not in df.columns
            or len(df) < 4
        ):
            return

        prices = df["close"].tail(4).astype(float).values

        if any(price == 0 for price in prices):
            return

        changes = [
            abs(prices[index] - prices[index - 1])
            / prices[index - 1]
            for index in range(1, 4)
        ]

        average_change = sum(changes) / len(changes)

        if average_change < self.MOMENTUM_THRESHOLD:
            return

        signal.momentum_acceleration = True

        net_change = (
            prices[-1] - prices[0]
        ) / prices[0]

        if net_change > 0:
            signal.direction = "up"
        elif net_change < 0:
            signal.direction = "down"

        logger.debug(
            "🔔 {}: تسارع الزخم {:.4f}",
            signal.symbol,
            average_change,
        )

    def _check_volatility_expansion(
        self,
        indicators: Any,
        signal: ExplosionSignal,
    ) -> None:
        """
        فحص توسع التقلب باستخدام ATR.
        """
        atr_pct = float(
            getattr(indicators, "atr_pct", 0.0)
        )

        if atr_pct >= 0.30:
            signal.volatility_expansion = True

            logger.debug(
                "🔔 {}: التقلب {:.3f}%",
                signal.symbol,
                atr_pct,
            )

    def _estimate_targets(
        self,
        df: pd.DataFrame,
        current_price: float,
        indicators: Any,
        signal: ExplosionSignal,
    ) -> None:
        """
        تقدير مستويات الحركة المحتملة.
        """
        atr_pct = float(
            getattr(indicators, "atr_pct", 0.0)
        )

        signal.estimated_move_pct = round(
            atr_pct * 3,
            3,
        )

        if (
            len(df) >= 20
            and "high" in df.columns
            and "low" in df.columns
        ):
            recent_high = float(
                df["high"].tail(20).max()
            )

            recent_low = float(
                df["low"].tail(20).min()
            )

            signal.key_level_above = round(
                recent_high,
                2,
            )

            signal.key_level_below = round(
                recent_low,
                2,
            )

    def _calculate_score(
        self,
        signal: ExplosionSignal,
    ) -> float:
        score = 0.0

        if signal.squeeze_detected:
            score += 0.30

        if signal.volume_surge:
            score += 0.25

        if signal.momentum_acceleration:
            score += 0.25

        if signal.volatility_expansion:
            score += 0.20

        return min(score, 1.0)

    def _calculate_confidence(
        self,
        signal: ExplosionSignal,
        indicators: Any,
    ) -> float:
        signals_count = sum(
            [
                signal.squeeze_detected,
                signal.volume_surge,
                signal.momentum_acceleration,
                signal.volatility_expansion,
            ]
        )

        confidence = signals_count / 4

        if signal.direction != "unknown":
            confidence += 0.10

        if getattr(
            indicators,
            "market_type",
            None,
        ) == "trending":
            confidence += 0.10

        return min(confidence, 1.0)

    def _determine_direction(
        self,
        df: pd.DataFrame,
        indicators: Any,
        current_price: float,
    ) -> str:
        bullish_signals = 0
        bearish_signals = 0

        ema_9 = getattr(
            indicators,
            "ema_9",
            0.0,
        )

        ema_21 = getattr(
            indicators,
            "ema_21",
            0.0,
        )

        if ema_9 > ema_21:
            bullish_signals += 1
        else:
            bearish_signals += 1

        macd_trend = getattr(
            indicators,
            "macd_trend",
            None,
        )

        if macd_trend == "bullish":
            bullish_signals += 1
        elif macd_trend == "bearish":
            bearish_signals += 1

        rsi = float(
            getattr(indicators, "rsi", 50.0)
        )

        if rsi > 50:
            bullish_signals += 1
        else:
            bearish_signals += 1

        bb_position = getattr(
            indicators,
            "bb_position",
            None,
        )

        if bb_position == "upper":
            bullish_signals += 1
        elif bb_position == "lower":
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            return "up"

        if bearish_signals > bullish_signals:
            return "down"

        return "unknown"
