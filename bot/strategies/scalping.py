# ======================================
# APEX TRADER - Scalping Strategy
# ======================================
# استراتيجية السكالبينق المتكاملة
# SNIPER / HUNTER / FARMER Modes
# بيانات حقيقية 100% من API

from dataclasses import dataclass
from typing import Optional, List, Tuple
from enum import Enum
import pandas as pd
from loguru import logger

from bot.signals.signal_engine import (
    SignalEngine,
    TradeSignal,
    TradeDirection,
    TradingMode
)
from bot.signals.indicators import TechnicalIndicators
from bot.core.fee_calculator import FeeCalculator
from bot.config import config


@dataclass
class ScalpingOpportunity:
    """
    فرصة سكالبينق مؤهلة
    تحتوي على كل المعلومات
    اللازمة للتنفيذ
    """
    signal: TradeSignal
    score: float                    # نقاط الجودة الكلية
    mode: TradingMode
    expected_profit_pct: float      # الربح المتوقع %
    expected_profit_usd: float      # الربح المتوقع $
    risk_reward_ratio: float        # نسبة المخاطرة/العائد
    recommended_leverage: int
    recommended_size_pct: float
    entry_reason: str               # سبب الدخول المختصر
    is_viable: bool                 # هل مجدية بعد العمولات؟


class ScalpingStrategy:
    """
    استراتيجية السكالبينق الاحترافية

    تعمل في 3 أوضاع:
    - SNIPER: صفقات نادرة عالية الجودة (90%+ ثقة)
    - HUNTER: صفقات متوازنة (70-90% ثقة)
    - FARMER: صفقات كثيرة سريعة (55-70% ثقة)

    + EXPLOSION: انفجارات سعرية (80%+ explosion score)
    """

    def __init__(self):
        self.signal_engine = SignalEngine()
        self.indicators = TechnicalIndicators()
        self.fee_calculator = FeeCalculator(
            exchange="binance"
        )
        logger.info("✅ Scalping Strategy جاهزة")

    def evaluate_opportunity(
        self,
        symbol: str,
        df: pd.DataFrame,
        current_price: float,
        balance: float,
        orderbook: Optional[dict] = None
    ) -> Optional[ScalpingOpportunity]:
        """
        تقييم شامل لفرصة التداول

        Args:
            symbol: رمز العملة
            df: بيانات الشموع الحقيقية
            current_price: السعر الحالي الحقيقي
            balance: الرصيد المتاح
            orderbook: دفتر الأوامر الحقيقي

        Returns:
            ScalpingOpportunity أو None
        """
        try:
            # تحليل الإشارة الكاملة
            signal = self.signal_engine.analyze(
                symbol=symbol,
                df=df,
                current_price=current_price,
                orderbook=orderbook
            )

            # إشارة غير صالحة؟
            if not signal.is_valid:
                return None

            # حساب نقاط الجودة
            score = self._calculate_opportunity_score(
                signal, df
            )

            # فلتر الجودة الأدنى
            if score < 0.50:
                logger.debug(
                    f"⏭️ {symbol}: نقاط منخفضة {score:.2f}"
                )
                return None

            # تحديد الليفريج والحجم
            leverage, size_pct = self._get_position_params(
                signal, score, balance
            )

            # حجم الصفقة الفعلي
            size_usd = balance * (size_pct / 100)
            position_value = size_usd * leverage

            # التحقق من الجدوى بعد العمولات
            fees = self.fee_calculator.calculate(
                position_value=position_value,
                entry_type="taker",
                exit_type="maker"
            )

            if not fees.is_viable:
                logger.debug(
                    f"⏭️ {symbol}: غير مجدية بعد العمولات"
                )
                return None

            # حساب الأرباح المتوقعة الحقيقية
            tp1_pct = config.risk.tp1_pct
            if signal.is_explosion:
                tp1_pct = config.risk.tp1_pct * 3

            # الربح بعد العمولات
            expected_profit_pct = (
                tp1_pct - fees.total_fee_pct
            )

            if expected_profit_pct <= 0:
                return None

            expected_profit_usd = (
                position_value * expected_profit_pct / 100
            )

            # نسبة المخاطرة/العائد
            sl_pct = config.risk.default_sl_pct
            risk_reward = (
                expected_profit_pct / sl_pct
                if sl_pct > 0 else 0
            )

            if risk_reward < 1.0:
                logger.debug(
                    f"⏭️ {symbol}: R:R ضعيف {risk_reward:.2f}"
                )
                return None

            # سبب الدخول المختصر
            entry_reason = self._build_entry_reason(signal)

            opportunity = ScalpingOpportunity(
                signal=signal,
                score=score,
                mode=signal.mode,
                expected_profit_pct=round(expected_profit_pct, 4),
                expected_profit_usd=round(expected_profit_usd, 4),
                risk_reward_ratio=round(risk_reward, 2),
                recommended_leverage=leverage,
                recommended_size_pct=size_pct,
                entry_reason=entry_reason,
                is_viable=True
            )

            logger.info(
                f"💡 فرصة مؤهلة: {symbol} "
                f"{signal.direction.value} | "
                f"نقاط: {score:.2f} | "
                f"R:R: {risk_reward:.2f} | "
                f"ربح متوقع: ${expected_profit_usd:.4f}"
            )

            return opportunity

        except Exception as e:
            logger.error(
                f"❌ خطأ تقييم فرصة {symbol}: {e}"
            )
            return None

    def _calculate_opportunity_score(
        self,
        signal: TradeSignal,
        df: pd.DataFrame
    ) -> float:
        """
        حساب نقاط جودة الفرصة الكلية
        من 0 (سيئة) إلى 1 (ممتازة)
        """
        score = 0.0

        ind = signal.indicators
        if not ind:
            return 0.0

        # 1. الثقة الأساسية (وزن 35%)
        score += signal.confidence * 0.35

        # 2. قوة الإشارة (وزن 20%)
        strength_scores = {
            "strong": 0.20,
            "moderate": 0.12,
            "weak": 0.04
        }
        score += strength_scores.get(
            ind.signal_strength, 0.04
        )

        # 3. Hurst Exponent (وزن 15%)
        # اتجاهي = أفضل للسكالبينق
        if ind.market_type == "trending":
            score += 0.15
        elif ind.market_type == "reverting":
            score += 0.08
        else:
            score += 0.03

        # 4. حجم التداول (وزن 15%)
        if ind.volume_ratio >= 2.0:
            score += 0.15   # حجم عالٍ = تأكيد قوي
        elif ind.volume_ratio >= 1.5:
            score += 0.10
        elif ind.volume_ratio >= 1.0:
            score += 0.06
        else:
            score += 0.01

        # 5. BB Squeeze (وزن 10%)
        if ind.bb_squeeze and signal.is_explosion:
            score += 0.10   # انفجار بعد ضغط = ممتاز

        # 6. Z-Score منطقي (وزن 5%)
        # سعر في نطاق طبيعي = أفضل
        if abs(ind.price_zscore) <= 1.5:
            score += 0.05
        elif abs(ind.price_zscore) <= 2.5:
            score += 0.02

        # مكافأة وضع الانفجار
        if signal.is_explosion:
            score += signal.explosion_score * 0.20

        return min(score, 1.0)

    def _get_position_params(
        self,
        signal: TradeSignal,
        score: float,
        balance: float
    ) -> Tuple[int, float]:
        """
        تحديد الليفريج وحجم الصفقة
        بناءً على الوضع والنقاط

        Returns:
            Tuple: (الليفريج, % من المحفظة)
        """
        mode = signal.mode

        # الليفريج حسب الوضع
        leverage_map = {
            TradingMode.SNIPER: config.trading.leverage_sniper,
            TradingMode.HUNTER: config.trading.leverage_hunter,
            TradingMode.FARMER: config.trading.leverage_farmer,
            TradingMode.EXPLOSION: min(
                15, config.risk.max_leverage
            )
        }
        base_leverage = leverage_map.get(
            mode, config.trading.leverage_hunter
        )

        # حجم الصفقة حسب الوضع والنقاط
        size_map = {
            TradingMode.SNIPER: 15.0,
            TradingMode.HUNTER: 8.0,
            TradingMode.FARMER: 3.0,
            TradingMode.EXPLOSION: 12.0
        }
        base_size = size_map.get(mode, 8.0)

        # تعديل الحجم بناءً على النقاط
        # نقاط أعلى = حجم أكبر
        adjusted_size = base_size * score

        # ضمان الحدود
        leverage = min(base_leverage, config.risk.max_leverage)
        size_pct = min(
            max(adjusted_size, 0.5),
            config.risk.max_position_pct
        )

        return leverage, round(size_pct, 2)

    def _build_entry_reason(self, signal: TradeSignal) -> str:
        """بناء سبب الدخول المختصر"""
        reasons = signal.reasons or []

        if signal.is_explosion:
            return f"💥 انفجار سعري | {' + '.join(reasons[:2])}"

        mode_labels = {
            TradingMode.SNIPER: "🎯 SNIPER",
            TradingMode.HUNTER: "🏹 HUNTER",
            TradingMode.FARMER: "🌾 FARMER"
        }

        label = mode_labels.get(signal.mode, "📊 SIGNAL")
        reason_text = " + ".join(reasons[:3]) if reasons else "إشارة تقنية"

        return f"{label} | {reason_text}"

    def rank_opportunities(
        self,
        opportunities: List[ScalpingOpportunity]
    ) -> List[ScalpingOpportunity]:
        """
        ترتيب الفرص حسب الجودة

        الأولوية:
        1. الانفجارات السعرية
        2. SNIPER
        3. HUNTER
        4. FARMER
        """
        def sort_key(opp: ScalpingOpportunity) -> float:
            mode_bonus = {
                TradingMode.EXPLOSION: 0.30,
                TradingMode.SNIPER: 0.20,
                TradingMode.HUNTER: 0.10,
                TradingMode.FARMER: 0.0
            }
            bonus = mode_bonus.get(opp.mode, 0.0)
            return opp.score + bonus

        return sorted(
            opportunities,
            key=sort_key,
            reverse=True
        )
