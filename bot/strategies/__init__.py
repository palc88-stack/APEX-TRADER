# bot/strategies/__init__.py
from bot.strategies.scalping import (
    ScalpingStrategy,
    ScalpingOpportunity
)
from bot.strategies.explosion import (
    ExplosionDetector,
    ExplosionSignal
)

__all__ = [
    "ScalpingStrategy",
    "ScalpingOpportunity",
    "ExplosionDetector",
    "ExplosionSignal"
]
