# ======================================
# APEX TRADER - Signals Package Init
# ======================================

from bot.signals.indicators import IndicatorCalculator, TechnicalIndicators
from bot.signals.filters import SignalFilters
from bot.signals.signal_engine import SignalEngine, TradeSignal, TradeDirection, TradingMode

# استيراد كاشف الانفجارات من مساره الصحيح
try:
    from bot.strategies.explosion import ExplosionDetector, ExplosionSignal, ExplosionStrategy
except ImportError:
    from bot.signals.explosion import ExplosionDetector, ExplosionSignal, ExplosionStrategy

# استيراد استراتيجية السكالبينج من مسار الاستراتيجيات الفعلي
try:
    from bot.strategies.scalping import ScalpingStrategy
except ImportError:
    from bot.signals.scalping import ScalpingStrategy

__all__ = [
    "IndicatorCalculator",
    "TechnicalIndicators",
    "SignalFilters",
    "SignalEngine",
    "TradeSignal",
    "TradeDirection",
    "TradingMode",
    "ExplosionDetector",
    "ExplosionSignal",
    "ExplosionStrategy",
    "ScalpingStrategy"
]
