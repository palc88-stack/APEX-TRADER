# ======================================
# APEX TRADER - Scalping Strategy
# ======================================

from dataclasses import dataclass
from typing import Optional, List, Tuple

import pandas as pd
from loguru import logger

from bot.signals.signal_engine import (
    SignalEngine,
    TradeSignal,
    TradingMode,
)
from bot.signals.indicators import TechnicalIndicators
from bot.core.fee_calculator import FeeCalculator
from bot.config import config


@dataclass
class ScalpingOpportunity:
    signal: TradeSignal
    score: float
    mode: TradingMode
    expected_profit_pct: float
    expected_profit_usd: float
    risk_reward_ratio: float
    recommended_leverage: int
    recommended_size_pct: float
    entry_reason: str
    is_viable: bool


class ScalpingStrategy:
    def __init__(self):
        self.signal_engine = SignalEngine()
        self.indicators = TechnicalIndicators()

        self.fee_calculator = FeeCalculator(
            exchange=config.exchange.primary_exchange()
        )

        logger.info(
            "✅ Scalping Strategy جاهزة"
        )

    def evaluate_opportunity(
        self,
        symbol: str,
        df: pd.DataFrame,
        current_price: float,
        balance: float,
        orderbook: Optional[dict] = None,
    ) -> Optional[ScalpingOpportunity]:
        try:
            signal = self.signal_engine.analyze(
                symbol=symbol,
                df=df,
                current_price=current_price,
                orderbook=orderbook,
            )

            if not signal.is_valid:
                return None

            score = self._calculate_opportunity_score(
                signal,
                df,
            )

            if score < 0.50:
                return None

            leverage, size_pct = (
                self._get_position_params(
                    signal,
                    score,
                    balance,
                )
            )

            size_usd = balance * (
                size_pct / 100
            )
            position_value = size_usd * leverage

            fees = self.fee_calculator.calculate(
                position_size=position_value,
                entry_type="taker",
                exit_type="maker",
                leverage=leverage,
            )

            if not fees.is_viable:
                return None

            tp1_pct = config.risk.tp1_pct

            if signal.is_explosion:
                tp1_pct *= 3

            expected_profit_pct = (
                tp1_pct - fees.total_fee_pct
            )

            if expected_profit_pct <= 0:
                return None

            expected_profit_usd = (
                position_value
                * expected_profit_pct
                / 100
            )

            sl_pct = config.risk.default_sl_pct

            risk_reward = (
                expected_profit_pct / sl_pct
                if sl_pct > 0
                else 0
            )

            if risk_reward < 1.0:
                return None

            return ScalpingOpportunity(
                signal=signal,
                score=score,
                mode=signal.mode,
                expected_profit_pct=round(
                    expected_profit_pct,
                    4,
                ),
                expected_profit_usd=round(
                    expected_profit_usd,
                    4,
                ),
                risk_reward_ratio=round(
                    risk_reward,
                    2,
                ),
                recommended_leverage=leverage,
                recommended_size_pct=size_pct,
                entry_reason=self._build_entry_reason(
                    signal
                ),
                is_viable=True,
            )

        except Exception as error:
            logger.exception(
                "❌ Error evaluating {}: {}",
                symbol,
                error,
            )
            return None

    def _calculate_opportunity_score(
        self,
        signal: TradeSignal,
        df: pd.DataFrame,
    ) -> float:
        score = 0.0
        indicators = signal.indicators

        if not indicators:
            return 0.0

        score += signal.confidence * 0.35

        strength_scores = {
            "strong": 0.20,
            "moderate": 0.12,
            "weak": 0.04,
        }

        score += strength_scores.get(
            indicators.signal_strength,
            0.04,
        )

        if indicators.market_type == "trending":
            score += 0.15
        elif indicators.market_type == "reverting":
            score += 0.08
        else:
            score += 0.03

        if indicators.volume_ratio >= 2.0:
            score += 0.15
        elif indicators.volume_ratio >= 1.5:
            score += 0.10
        elif indicators.volume_ratio >= 1.0:
            score += 0.06
        else:
            score += 0.01

        if (
            indicators.bb_squeeze
            and signal.is_explosion
        ):
            score += 0.10

        if abs(indicators.price_zscore) <= 1.5:
            score += 0.05
        elif abs(indicators.price_zscore) <= 2.5:
            score += 0.02

        if signal.is_explosion:
            score += signal.explosion_score * 0.20

        return min(score, 1.0)

    def _get_position_params(
        self,
        signal: TradeSignal,
        score: float,
        balance: float,
    ) -> Tuple[int, float]:
        leverage_map = {
            TradingMode.SNIPER:
                config.trading.leverage_sniper,
            TradingMode.HUNTER:
                config.trading.leverage_hunter,
            TradingMode.FARMER:
                config.trading.leverage_farmer,
            TradingMode.EXPLOSION:
                min(15, config.risk.max_leverage),
        }

        size_map = {
            TradingMode.SNIPER: 15.0,
            TradingMode.HUNTER: 8.0,
            TradingMode.FARMER: 3.0,
            TradingMode.EXPLOSION: 12.0,
        }

        base_leverage = leverage_map.get(
            signal.mode,
            config.trading.leverage_hunter,
        )

        base_size = size_map.get(
            signal.mode,
            8.0,
        )

        adjusted_size = base_size * score

        leverage = min(
            base_leverage,
            config.risk.max_leverage,
        )

        size_pct = min(
            max(adjusted_size, 0.5),
            config.risk.max_position_pct,
        )

        return leverage, round(size_pct, 2)

    def _build_entry_reason(
        self,
        signal: TradeSignal,
    ) -> str:
        reasons = signal.reasons or []

        if signal.is_explosion:
            return (
                "💥 انفجار سعري | "
                f"{' + '.join(reasons[:2])}"
            )

        labels = {
            TradingMode.SNIPER: "🎯 SNIPER",
            TradingMode.HUNTER: "🏹 HUNTER",
            TradingMode.FARMER: "🌾 FARMER",
        }

        label = labels.get(
            signal.mode,
            "📊 SIGNAL",
        )

        reason_text = (
            " + ".join(reasons[:3])
            if reasons
            else "إشارة تقنية"
        )

        return f"{label} | {reason_text}"

    def rank_opportunities(
        self,
        opportunities: List[ScalpingOpportunity],
    ) -> List[ScalpingOpportunity]:
        mode_bonus = {
            TradingMode.EXPLOSION: 0.30,
            TradingMode.SNIPER: 0.20,
            TradingMode.HUNTER: 0.10,
            TradingMode.FARMER: 0.0,
        }

        return sorted(
            opportunities,
            key=lambda opportunity: (
                opportunity.score
                + mode_bonus.get(
                    opportunity.mode,
                    0.0,
                )
            ),
            reverse=True,
        )
