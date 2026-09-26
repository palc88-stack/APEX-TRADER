"""
bot/strategies/explosion.py — الكود المُصحَّح (خلل حرج #2 + #6)

سبب الإصلاح:
────────────
1) التوقيع (signature) الأصلي كان:
       def detect(self, symbol, df, indicators, current_price)
   بينما signal_engine.py يستدعيه فعلياً بـ:
       self.explosion_detector.detect(df_analyzed, symbol)
   → هذا يسبب TypeError مؤكّدة (تم تشغيلها فعلياً وتأكيدها) في كل دورة تداول،
     ما يجعل استراتيجية "الانفجار السعري" معطّلة 100% بصمت.

2) الباراميتر "indicators" في النسخة الأصلية كان متوقَّعاً ككائن يملك خصائص مثل
   bb_squeeze / volume_ratio / atr_pct / ema_9 / ema_21 / macd_trend / bb_position /
   market_type — وهذه الخصائص غير موجودة في أي مكان آخر بالمشروع (تم التأكد بالبحث
   الشامل في الريبو بالكامل). أي أن الملف كُتب أصلاً لواجهة مؤشرات لا وجود لها،
   وهذا خلل بنيوي (architecture mismatch) وليس مجرد خطأ كتابي.

3) `_determine_direction` كانت تُرجع "up" / "down" بينما signal_engine.py يتحقق من
   القيمة "LONG" حصراً (`"LONG" if explosion_signal.direction == "LONG" else ...`),
   ما يعني أنه حتى لو أُصلح التوقيع فقط، ستُقرأ كل الإشارات الصاعدة كإشارة بيع (SELL)
   بشكل معكوس تماماً.

الحل: إعادة كتابة الكاشف بالكامل ليعمل مباشرة على الـ DataFrame المُحلَّل الذي
تنتجه IndicatorCalculator فعلياً (rsi, macd, macd_signal, bb_upper/middle/lower,
ema_50, ema_200, volume, close, high, low) دون أي بيانات وهمية، ويُرجع
direction بصيغة "LONG"/"SHORT" المتوافقة مع باقي النظام.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger


@dataclass
class ExplosionSignal:
    """إشارة انفجار سعري محتمل."""

    symbol: str
    direction: str          # "LONG" | "SHORT" | "UNKNOWN"
    score: float
    confidence: float

    squeeze_detected: bool = False
    volume_surge: bool = False
    volatility_expansion: bool = False
    momentum_acceleration: bool = False

    estimated_move_pct: float = 0.0
    key_level_above: float = 0.0
    key_level_below: float = 0.0
    reason: str = ""

    @property
    def is_valid(self) -> bool:
        return (
            self.score >= 0.70
            and self.confidence >= 0.65
            and self.direction in ("LONG", "SHORT")
        )


class ExplosionDetector:
    """
    كاشف الحركات السعرية الحادة — يعمل مباشرة على بيانات OHLCV الحقيقية
    + المؤشرات التي تحسبها IndicatorCalculator فعلياً. لا بيانات وهمية.

    يعتمد على:
    - انضغاط/انفراج نطاق Bollinger (bb squeeze / breakout)
    - ارتفاع حجم التداول النسبي (مقارنة بمتوسط آخر 20 شمعة)
    - تسارع الزخم على آخر 4 شموع
    - توسع التقلب (ATR% تقديري من الـ True Range)
    """

    VOLUME_SURGE_RATIO = 2.0        # ضعف متوسط الحجم فأكثر
    MOMENTUM_THRESHOLD = 0.003      # 0.3% متوسط تغيّر لكل شمعة
    ATR_EXPANSION_PCT = 0.30        # ATR% >= 0.30 يعتبر توسّع تقلب
    MIN_SCORE_FOR_SIGNAL = 0.60
    BB_SQUEEZE_WIDTH_RATIO = 0.70   # عرض البولنجر الحالي / متوسط آخر 20 يوم

    def detect(self, df: pd.DataFrame, symbol: str) -> Optional[ExplosionSignal]:
        """
        اكتشاف انفجار سعري محتمل من DataFrame مُحلَّل (يحتوي أعمدة المؤشرات).

        Args:
            df: DataFrame بعد تمريره على IndicatorCalculator.calculate_all()
            symbol: رمز التداول
        """
        try:
            if df is None or df.empty or len(df) < 25:
                return None

            required = ["close", "high", "low", "volume", "rsi", "macd", "macd_signal",
                        "bb_upper", "bb_middle", "bb_lower", "ema_50", "ema_200"]
            for col in required:
                if col not in df.columns:
                    logger.warning("⚠️ ExplosionDetector: عمود مفقود {}", col)
                    return None

            signal = ExplosionSignal(symbol=symbol, direction="UNKNOWN", score=0.0, confidence=0.0)

            latest = df.iloc[-1]
            current_price = float(latest["close"])

            self._check_bb_squeeze(df, signal)
            self._check_volume_surge(df, signal)
            self._check_momentum(df, signal)
            self._check_volatility_expansion(df, signal)
            self._estimate_targets(df, current_price, signal)

            signal.score = self._calculate_score(signal)
            if signal.score < self.MIN_SCORE_FOR_SIGNAL:
                return None

            signal.direction = self._determine_direction(df)
            if signal.direction == "UNKNOWN":
                return None

            signal.confidence = self._calculate_confidence(signal)
            signal.reason = (
                f"Explosion setup: squeeze={signal.squeeze_detected}, "
                f"vol_surge={signal.volume_surge}, momentum={signal.momentum_acceleration}, "
                f"volatility={signal.volatility_expansion}"
            )

            if not signal.is_valid:
                return None

            logger.info(
                "💥 انفجار محتمل: {} | النقاط: {:.2f} | الاتجاه: {} | الحركة المتوقعة: {:.2f}%",
                symbol, signal.score, signal.direction, signal.estimated_move_pct,
            )
            return signal

        except Exception as error:
            logger.error("❌ خطأ في كشف الانفجار للرمز {}: {}", symbol, error)
            return None

    # ── الفحوصات الفرعية ────────────────────────────────────────────────

    def _check_bb_squeeze(self, df: pd.DataFrame, signal: ExplosionSignal) -> None:
        """انضغاط بولنجر (تقلب منخفض) قد يسبق انفجاراً سعرياً."""
        bb_width = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"].replace(0, pd.NA)
        bb_width = bb_width.dropna()
        if len(bb_width) < 20:
            return
        current_width = float(bb_width.iloc[-1])
        avg_width = float(bb_width.tail(20).mean())
        if avg_width > 0 and current_width <= avg_width * self.BB_SQUEEZE_WIDTH_RATIO:
            signal.squeeze_detected = True

    def _check_volume_surge(self, df: pd.DataFrame, signal: ExplosionSignal) -> None:
        """ارتفاع حجم التداول الحالي عن متوسط آخر 20 شمعة."""
        if len(df) < 20:
            return
        current_volume = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].tail(20).mean())
        if avg_volume > 0 and (current_volume / avg_volume) >= self.VOLUME_SURGE_RATIO:
            signal.volume_surge = True

    def _check_momentum(self, df: pd.DataFrame, signal: ExplosionSignal) -> None:
        """تسارع الزخم في آخر 4 شموع."""
        if len(df) < 4:
            return
        prices = df["close"].tail(4).astype(float).values
        if any(p == 0 for p in prices):
            return
        changes = [abs(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, 4)]
        avg_change = sum(changes) / len(changes)
        if avg_change >= self.MOMENTUM_THRESHOLD:
            signal.momentum_acceleration = True

    def _check_volatility_expansion(self, df: pd.DataFrame, signal: ExplosionSignal) -> None:
        """توسّع التقلب عبر ATR% تقديري (True Range) على آخر 14 شمعة."""
        if len(df) < 15:
            return
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.tail(14).mean()
        current_close = float(close.iloc[-1])
        if current_close > 0:
            atr_pct = float(atr / current_close * 100)
            if atr_pct >= self.ATR_EXPANSION_PCT:
                signal.volatility_expansion = True

    def _estimate_targets(self, df: pd.DataFrame, current_price: float, signal: ExplosionSignal) -> None:
        """تقدير مدى الحركة المحتملة ومستويات الدعم/المقاومة القريبة."""
        if len(df) >= 14:
            high, low, close = df["high"], df["low"], df["close"]
            prev_close = close.shift(1)
            tr = pd.concat([
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.tail(14).mean())
            signal.estimated_move_pct = round((atr / current_price * 100) * 3, 3) if current_price else 0.0

        if len(df) >= 20:
            signal.key_level_above = round(float(df["high"].tail(20).max()), 6)
            signal.key_level_below = round(float(df["low"].tail(20).min()), 6)

    def _calculate_score(self, signal: ExplosionSignal) -> float:
        score = 0.0
        if signal.squeeze_detected:
            score += 0.25
        if signal.volume_surge:
            score += 0.30
        if signal.momentum_acceleration:
            score += 0.25
        if signal.volatility_expansion:
            score += 0.20
        return min(score, 1.0)

    def _calculate_confidence(self, signal: ExplosionSignal) -> float:
        signals_count = sum([
            signal.squeeze_detected,
            signal.volume_surge,
            signal.momentum_acceleration,
            signal.volatility_expansion,
        ])
        confidence = signals_count / 4
        if signal.direction in ("LONG", "SHORT"):
            confidence += 0.10
        return min(confidence, 1.0)

    def _determine_direction(self, df: pd.DataFrame) -> str:
        """
        تحديد اتجاه الانفجار من مؤشرات حقيقية موجودة فعلاً في الـ DataFrame:
        EMA50 مقابل EMA200 (اتجاه)، MACD مقابل خط الإشارة، RSI، موقع السعر من
        نطاق Bollinger. يُرجع "LONG" أو "SHORT" فقط (متوافق مع signal_engine.py)
        أو "UNKNOWN" إذا تعادلت الإشارات.
        """
        latest = df.iloc[-1]
        bullish, bearish = 0, 0

        ema_50 = float(latest.get("ema_50", 0.0))
        ema_200 = float(latest.get("ema_200", 0.0))
        if ema_50 > ema_200:
            bullish += 1
        elif ema_50 < ema_200:
            bearish += 1

        macd = float(latest.get("macd", 0.0))
        macd_signal = float(latest.get("macd_signal", 0.0))
        if macd > macd_signal:
            bullish += 1
        elif macd < macd_signal:
            bearish += 1

        rsi = float(latest.get("rsi", 50.0))
        if rsi > 50:
            bullish += 1
        else:
            bearish += 1

        close = float(latest.get("close", 0.0))
        bb_upper = float(latest.get("bb_upper", close))
        bb_lower = float(latest.get("bb_lower", close))
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_position = (close - bb_lower) / bb_range
            if bb_position >= 0.7:
                bullish += 1
            elif bb_position <= 0.3:
                bearish += 1

        if bullish > bearish:
            return "LONG"
        if bearish > bullish:
            return "SHORT"
        return "UNKNOWN"
