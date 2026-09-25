# ======================================
# APEX TRADER - Signals Package Init
# ======================================

from bot.signals.indicators import IndicatorCalculator, TechnicalIndicators
from bot.signals.filters import SignalFilters
from bot.signals.signal_engine import SignalEngine, TradeSignal, TradeDirection, TradingMode

# استيراد كاشف الانفجارات من المسار الصحيح (bot.strategies.explosion)
try:
    from bot.strategies.explosion import ExplosionDetector, ExplosionSignal, ExplosionStrategy
except ImportError:
    try:
        # مسار احتياطي ثانٍ إن وجد
        from bot.signals.explosion import ExplosionDetector, ExplosionSignal, ExplosionStrategy
    except ImportError:
        ExplosionDetector = None
        ExplosionSignal = None
        ExplosionStrategy = None

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
