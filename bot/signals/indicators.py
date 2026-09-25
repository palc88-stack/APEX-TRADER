from typing import Any, Dict, Optional, Tuple

import pandas as pd
from loguru import logger


class IndicatorCalculator:
    """
    حاسب المؤشرات الفنية لنظام التداول الآلي.
    يعتمد على بيانات OHLCV الحقيقية فقط.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        حساب المؤشرات الفنية المطلوبة.
        """
        if df is None or df.empty:
            logger.warning(
                "⚠️ محاولة حساب المؤشرات لإطار بياني فارغ."
            )
            return df

        required_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        for column in required_columns:
            if column not in df.columns:
                logger.error(
                    "❌ العمود الأساسي مفقود في البيانات: {}",
                    column,
                )
                return df

        try:
            result = df.copy()

            result["sma_20"] = self.calculate_sma(
                result,
                period=20,
            )

            result["ema_50"] = self.calculate_ema(
                result,
                period=50,
            )

            result["ema_200"] = self.calculate_ema(
                result,
                period=200,
            )

            result["rsi"] = self.calculate_rsi(
                result,
                period=14,
            )

            macd, macd_signal, macd_hist = (
                self.calculate_macd(
                    result,
                    fast=12,
                    slow=26,
                    signal_period=9,
                )
            )

            result["macd"] = macd
            result["macd_signal"] = macd_signal
            result["macd_hist"] = macd_hist

            bb_upper, bb_middle, bb_lower = (
                self.calculate_bollinger_bands(
                    result,
                    period=20,
                    std_dev=2.0,
                )
            )

            result["bb_upper"] = bb_upper
            result["bb_middle"] = bb_middle
            result["bb_lower"] = bb_lower

            logger.debug(
                "✅ تم حساب المؤشرات بنجاح على {} شمعة.",
                len(result),
            )

            return result

        except Exception as error:
            logger.error(
                "❌ خطأ أثناء حساب المؤشرات الفنية: {}",
                error,
            )
            return df

    @staticmethod
    def calculate_sma(
        df: pd.DataFrame,
        period: int = 20,
    ) -> pd.Series:
        return df["close"].rolling(
            window=period,
            min_periods=period,
        ).mean()

    @staticmethod
    def calculate_ema(
        df: pd.DataFrame,
        period: int = 50,
    ) -> pd.Series:
        return df["close"].ewm(
            span=period,
            adjust=False,
            min_periods=1,
        ).mean()

    @staticmethod
    def calculate_rsi(
        df: pd.DataFrame,
        period: int = 14,
    ) -> pd.Series:
        close = df["close"].astype(float)
        delta = close.diff()

        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)

        average_gain = gains.rolling(
            window=period,
            min_periods=period,
        ).mean()

        average_loss = losses.rolling(
            window=period,
            min_periods=period,
        ).mean()

        relative_strength = average_gain / (
            average_loss + 1e-12
        )

        return 100.0 - (
            100.0 / (1.0 + relative_strength)
        )

    @staticmethod
    def calculate_macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal_period: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        close = df["close"].astype(float)

        fast_ema = close.ewm(
            span=fast,
            adjust=False,
            min_periods=1,
        ).mean()

        slow_ema = close.ewm(
            span=slow,
            adjust=False,
            min_periods=1,
        ).mean()

        macd = fast_ema - slow_ema

        signal = macd.ewm(
            span=signal_period,
            adjust=False,
            min_periods=1,
        ).mean()

        histogram = macd - signal

        return macd, signal, histogram

    @staticmethod
    def calculate_bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        close = df["close"].astype(float)

        middle = close.rolling(
            window=period,
            min_periods=period,
        ).mean()

        standard_deviation = close.rolling(
            window=period,
            min_periods=period,
        ).std()

        upper = middle + (
            standard_deviation * std_dev
        )

        lower = middle - (
            standard_deviation * std_dev
        )

        return upper, middle, lower


class TechnicalIndicators(IndicatorCalculator):
    """
    توافق مع أي كود يستورد TechnicalIndicators.
    """

    pass
