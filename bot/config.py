# bot/config.py — إعدادات APEX TRADER الكاملة

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _env_text(name: str, default: str = "") -> str:
    return os.getenv(name, default or "")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Exchange
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExchangeConfig:
    binance_api_key: str = field(default_factory=lambda: _env_text("BINANCE_API_KEY"))
    binance_secret_key: str = field(default_factory=lambda: _env_text("BINANCE_SECRET_KEY"))
    binance_testnet: bool = field(default_factory=lambda: _env_bool("BINANCE_TESTNET", True))

    bybit_api_key: str = field(default_factory=lambda: _env_text("BYBIT_API_KEY"))
    bybit_secret_key: str = field(default_factory=lambda: _env_text("BYBIT_SECRET_KEY"))
    bybit_testnet: bool = field(default_factory=lambda: _env_bool("BYBIT_TESTNET", True))

    _primary_exchange: str = field(default_factory=lambda: _env_text("PRIMARY_EXCHANGE", "binance"))
    # رسوم Binance
    binance_maker_fee: float = field(default_factory=lambda: _env_float("BINANCE_MAKER_FEE", 0.0002))
    binance_taker_fee: float = field(default_factory=lambda: _env_float("BINANCE_TAKER_FEE", 0.0004))
    # رسوم Bybit
    bybit_maker_fee: float = field(default_factory=lambda: _env_float("BYBIT_MAKER_FEE", 0.0002))
    bybit_taker_fee: float = field(default_factory=lambda: _env_float("BYBIT_TAKER_FEE", 0.00055))

    def primary_exchange(self) -> str:
        """إرجاع اسم المنصة الأساسية lowercase"""
        return self._primary_exchange.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Database (Supabase)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DatabaseConfig:
    supabase_url: str = field(default_factory=lambda: _env_text("SUPABASE_URL"))
    supabase_key: str = field(default_factory=lambda: _env_text("SUPABASE_KEY"))


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TelegramConfig:
    bot_token: str = field(default_factory=lambda: _env_text("TELEGRAM_BOT_TOKEN"))
    chat_id: str = field(default_factory=lambda: _env_text("TELEGRAM_CHAT_ID"))


# ─────────────────────────────────────────────────────────────────────────────
# Risk
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskConfig:
    max_daily_loss_pct: float = field(default_factory=lambda: _env_float("MAX_DAILY_LOSS_PCT", 4.0))
    max_leverage: int = field(default_factory=lambda: _env_int("MAX_LEVERAGE", 20))
    default_sl_pct: float = field(default_factory=lambda: _env_float("DEFAULT_SL_PCT", 1.5))
    tp1_pct: float = field(default_factory=lambda: _env_float("TP1_PCT", 1.0))
    tp2_pct: float = field(default_factory=lambda: _env_float("TP2_PCT", 2.5))
    max_position_pct: float = field(default_factory=lambda: _env_float("MAX_POSITION_PCT", 5.0))
    min_confidence: float = field(default_factory=lambda: _env_float("MIN_CONFIDENCE", 0.65))
    breakeven_pct: float = field(default_factory=lambda: _env_float("BREAKEVEN_PCT", 0.15))
    trailing_activation_pct: float = field(default_factory=lambda: _env_float("TRAILING_ACTIVATION_PCT", 0.30))


# ─────────────────────────────────────────────────────────────────────────────
# Trading
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradingConfig:
    symbols: List[str] = field(
        default_factory=lambda: [
            s.strip().upper()
            for s in _env_text("TRADING_SYMBOLS", "BTC/USDT").split(",")
            if s.strip()
        ] or ["BTC/USDT"]
    )
    timeframe: str = field(default_factory=lambda: _env_text("TRADING_TIMEFRAME", "5m"))


# ─────────────────────────────────────────────────────────────────────────────
# Config الرئيسي
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)

    initial_balance: float = field(default_factory=lambda: _env_float("INITIAL_BALANCE", 100.0))
    active_mode: str = field(default_factory=lambda: _env_text("ACTIVE_MODE", "HUNTER").upper())
    environment: str = field(default_factory=lambda: _env_text("ENVIRONMENT", "testnet"))


# ── Module-level instance للاستيراد المباشر (market_data.py و telegram_notifier.py يستخدمانه) ──
config = Config()
