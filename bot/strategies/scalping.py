import pandas as pd
from typing import Dict, Any, Optional
from loguru import logger


class ScalpingStrategy:
    """
    استراتيجية السكالبينج اللحظي (Scalping Strategy) لمنظومة (Apex Trader).
    تستهدف اقتناص الحركات السعرية السريعة والقصيرة بناءً على السيولة والزخم الحقيقي.
    خالية تماماً من أي بيانات وهمية أو افتراضية.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.target_profit_pct = float(self.config.get("scalp_take_profit_pct", 0.005))  # 0.5%
        self.max_stop_loss_pct = float(self.config.get("scalp_stop_loss_pct", 0.003))    # 0.3%

    def evaluate_scalp_setup(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        """
        تقييم فرصة سكالبينج حقيقية بناءً على الشموع الأخيرة ومؤشرات الزخم والبولنجر.
        """
        setup = {
            "symbol": symbol,
            "action": "HOLD",
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "reason": "No scalping setup found"
        }

        if df is None or df.empty or len(df) < 30:
            return setup

        try:
            latest = df.iloc[-1]
            close = float(latest.get('close', 0.0))
            bb_lower = float(latest.get('bb_lower', close))
            bb_upper = float(latest.get('bb_upper', close))
            rsi = float(latest.get('rsi', 50.0))

            if close <= 0:
                return setup

            # شروط سكالبينج حقيقية: ملامسة الحد السفلي لبولنجر مع تشبع بيعي RSI
            if close <= bb_lower and rsi < 35:
                setup["action"] = "BUY"
                setup["entry_price"] = close
                setup["stop_loss"] = round(close * (1.0 - self.max_stop_loss_pct), 4)
                setup["take_profit"] = round(close * (1.0 + self.target_profit_pct), 4)
                setup["reason"] = "Price touched lower Bollinger band with RSI oversold."
                logger.info("⚡ فرصة سكالبينج شراء للرمز {}: السعر={}, SL={}, TP={}", symbol, close, setup["stop_loss"], setup["take_profit"])

            # شروط سكالبينج حقيقية: ملامسة الحد العلوي لبولنجر مع تشبع شرائي RSI
            elif close >= bb_upper and rsi > 65:
                setup["action"] = "SELL"
                setup["entry_price"] = close
                setup["stop_loss"] = round(close * (1.0 + self.max_stop_loss_pct), 4)
                setup["take_profit"] = round(close * (1.0 - self.target_profit_pct), 4)
                setup["reason"] = "Price touched upper Bollinger band with RSI overbought."
                logger.info("⚡ فرصة سكالبينج بيع للرمز {}: السعر={}, SL={}, TP={}", symbol, close, setup["stop_loss"], setup["take_profit"])

            return setup

        except Exception as error:
            logger.error("❌ خطأ في استراتيجية السكالبينج للرمز {}: {}", symbol, error)
            return setup
