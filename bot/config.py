# ======================================
# APEX TRADER - Configuration
# ======================================

import math
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"Invalid boolean value for {name}: {value!r}. "
        "Expected one of: true, false, 1, 0, yes, no, on, off."
    )


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return float(default)
    try:
        result = float(value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid numeric value for {name}: {value!r}. "
            f"Expected a decimal number. Default is {default}."
        ) from exc
    if not math.isfinite(result):
        raise ValueError(
            f"Invalid non-finite value for {name}: {value!r}."
        )
    return result


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return int(default)
    try:
        return int(value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid integer value for {name}: {value!r}. "
            f"Expected an integer. Default is {default}."
        ) from exc


@dataclass
class ExchangeConfig:
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = False

    bybit_api_key: str = ""
    bybit_secret_key: str = ""
    bybit_testnet: bool = False

    def __post_init__(self) -> None:
        self.binance_api_key = _env_text("BINANCE_API_KEY", self.binance_api_key)
        self.binance_secret_key = _env_text("BINANCE_SECRET_KEY", self.binance_secret_key)
        self.binance_testnet = _env_bool("BINANCE_TESTNET", self.binance_testnet)

        self.bybit_api_key = _env_text("BYBIT_API_KEY", self.bybit_api_key)
        self.bybit_secret_key = _env_text("BYBIT_SECRET_KEY", self.bybit_secret_key)
        self.bybit_testnet = _env_bool("BYBIT_TESTNET", self.bybit_testnet)

    def validate(self) -> bool:
        return bool(self.binance_api_key or self.bybit_api_key)


@dataclass
class DatabaseConfig:
    supabase_url: str = ""
    supabase_key: str = ""
    redis_url: str = ""
    redis_token: str = ""

    def __post_init__(self) -> None:
        self.supabase_url = _env_text("SUPABASE_URL", self.supabase_url)
        self.supabase_key = _env_text("SUPABASE_KEY", self.supabase_key)
        self.redis_url = _env_text("UPSTASH_REDIS_URL", self.redis_url)
        self.redis_token = _env_text("UPSTASH_REDIS_TOKEN", self.redis_token)

    def validate(self) -> bool:
        return bool(self.supabase_url and self.supabase_key) or bool(self.redis_url)


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    def __post_init__(self) -> None:
        self.bot_token = _env_text("TELEGRAM_BOT_TOKEN", self.bot_token)
        self.chat_id = _env_text("TELEGRAM_CHAT_ID", self.chat_id)

    def validate(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class RiskConfig:
    max_daily_loss_pct: float = 4.0
    max_leverage: int = 10
    default_sl_pct: float = 0.5
    tp1_pct: float = 1.2
    tp2_pct: float = 2.5
    compounding_rate: float = 0.1
    max_position_pct: float = 20.0

    breakeven_pct: float = 0.15
    trailing_activation_pct: float = 0.30
    binance_maker_fee: float = 0.0002
    binance_taker_fee: float = 0.0004
    bybit_maker_fee: float = 0.0002
    bybit_taker_fee: float = 0.00055

    def __post_init__(self) -> None:
        self.max_daily_loss_pct = _env_float("MAX_DAILY_LOSS_PCT", self.max_daily_loss_pct)
        self.max_leverage = _env_int("MAX_LEVERAGE", self.max_leverage)
        self.default_sl_pct = _env_float("DEFAULT_SL_PCT", self.default_sl_pct)
        self.tp1_pct = _env_float("TP1_PCT", self.tp1_pct)
        self.tp2_pct = _env_float("TP2_PCT", self.tp2_pct)
        self.compounding_rate = _env_float("COMPOUNDING_RATE", self.compounding_rate)
        self.max_position_pct = _env_float("MAX_POSITION_PCT", self.max_position_pct)
        self.breakeven_pct = _env_float("BREAKEVEN_PCT", self.breakeven_pct)
        self.trailing_activation_pct = _env_float(
            "TRAILING_ACTIVATION_PCT",
            self.trailing_activation_pct,
        )
        self.binance_maker_fee = _env_float("BINANCE_MAKER_FEE", self.binance_maker_fee)
        self.binance_taker_fee = _env_float("BINANCE_TAKER_FEE", self.binance_taker_fee)
        self.bybit_maker_fee = _env_float("BYBIT_MAKER_FEE", self.bybit_maker_fee)
        self.bybit_taker_fee = _env_float("BYBIT_TAKER_FEE", self.bybit_taker_fee)


@dataclass
class TradingConfig:
    symbols: List[str] = field(
        default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    )
    timeframe: str = "5m"
    min_confidence_sniper: float = 0.75
    min_confidence_hunter: float = 0.60
    min_confidence_farmer: float = 0.55
    leverage_sniper: int = 8
    leverage_hunter: int = 5
    leverage_farmer: int = 3

    def __post_init__(self) -> None:
        symbols_env = os.getenv("TRADING_SYMBOLS")
        if symbols_env and symbols_env.strip():
            self.symbols = [
                s.strip() for s in symbols_env.split(",") if s.strip()
            ]

        self.timeframe = _env_text("TRADING_TIMEFRAME", self.timeframe)
        self.min_confidence_sniper = _env_float("MIN_CONFIDENCE_SNIPER", self.min_confidence_sniper)
        self.min_confidence_hunter = _env_float("MIN_CONFIDENCE_HUNTER", self.min_confidence_hunter)
        self.min_confidence_farmer = _env_float("MIN_CONFIDENCE_FARMER", self.min_confidence_farmer)
        self.leverage_sniper = _env_int("LEVERAGE_SNIPER", self.leverage_sniper)
        self.leverage_hunter = _env_int("LEVERAGE_HUNTER", self.leverage_hunter)
        self.leverage_farmer = _env_int("LEVERAGE_FARMER", self.leverage_farmer)


@dataclass
class AppConfig:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)

    def validate_all(self) -> bool:
        return (
            self.exchange.validate()
            and self.database.validate()
            and self.telegram.validate()
        )

    def reload(self) -> None:
        self.exchange = ExchangeConfig()
        self.database = DatabaseConfig()
        self.telegram = TelegramConfig()
        self.risk = RiskConfig()
        self.trading = TradingConfig()


config = AppConfig()
