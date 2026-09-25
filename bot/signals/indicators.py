import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
from loguru import logger


class IndicatorCalculator:
    """
    مُحسب المؤشرات الفنية المتقدمة لنظام التداول الآلي (Apex Trader).
    يقوم بحساب المؤشرات بناءً على بيانات الشموع الحية (OHLCV) الواردة من المنصات.
    خالٍ تماماً من أي بيانات وهمية أو افتراضية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        حساب كافة المؤشرات الفنية المطلوبة للتحليل الفني واستراتيجيات السكالبينج والانفجار
        بناءً على الشموع الحقيقية حصرياً.
        """
        if df is None or df.empty:
            logger.warning("⚠️ محاولة حساب المؤشرات لإطار بياني فارغ (DataFrame is empty).")
            return df

        try:
            # التحقق من وجود أعمدة الشموع الأساسية
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in required_columns:
                if col not in df.columns:
                    logger.error("❌ العمود الأساسي مفقود في البيانات الحية: {}", col)
                    return df

            # حساب المتوسطات المتحركة الأسية والبسيطة الحقيقية
            df['sma_20'] = self.calculate_sma(df, period=20)
            df['ema_50'] = self.calculate_ema(df, period=50)
            df['ema_200'] = self.calculate_ema(df, period=200)

            # مؤشر القوة النسبية الحقيقي (RSI)
            df['rsi'] = self.calculate_rsi(df, period=14)

            # مؤشر الماكد الحقيقي (MACD)
            macd, signal, hist = self.calculate_macd(df)
            df['macd'] = macd
            df['macd_signal'] = signal
            df['macd_hist'] = hist

            # حدود بولنجر باند الحقيقية (Bollinger Bands)
            upper, middle, lower = self.calculate_bollinger_bands(df)
            df['bb_upper'] = upper
            df['bb_middle'] = middle
            df['bb_lower'] = lower

            logger.debug("✅ تم حساب جميع المؤشرات الفنية الحقيقية بنجاح على إطار بحجم {} شمعة.", len(df))
            return df

        except Exception as error:
            logger.error("❌ خطأ أثناء حساب المؤشرات الفنية الحقيقية: {}", error)
            return df

    @staticmethod
    def calculate_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
        return df['close'].rolling(window=period).mean()

    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int = 50) -> pd.Series:
        return df['close'].ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        close = df['close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        # تجنب القسمة على صفر باستخدام قيمة رياضية دقيقة
        rs = gain / (loss + 1e-12)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        close = df['close']
        exp1 = close.ewm(span=fast, adjust=False).mean()
        exp2 = close.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        hist = macd - signal
        return macd, signal, hist

    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        close = df['close']
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower
