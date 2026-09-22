# ======================================
# APEX TRADER - Configuration
# ======================================

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass
class ExchangeConfig:
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = False

    bybit_api_key: str = ""
    bybit_secret_key: str = ""
    bybit_testnet: bool = False

    def __post_init__(self):
        self.binance_api_key = os.getenv("BINANCE_API_KEY", self.binance_api_key)
        self.binance_secret_key = os.getenv("BINANCE_SECRET_KEY", self.binance_secret_key)
        self.binance_testnet = (
            os.getenv("BINANCE_TESTNET", "false").strip().lower() in {"1", "true", "yes"}
        )

        self.bybit_api_key = os.getenv("BYBIT_API_KEY", self.bybit_api_key)
        self.bybit_secret_key = os.getenv("BYBIT_SECRET_KEY", self.bybit_secret_key)
        self.bybit_testnet = (
            os.getenv("BYBIT_TESTNET", "false").strip().lower() in {"1", "true", "yes"}
        )

    def validate(self) -> bool:
        return bool(self.binance_api_key or self.bybit_api_key)


@dataclass
class DatabaseConfig:
    supabase_url: str = ""
    supabase_key: str = ""
    redis_url: str = ""
    redis_token: str = ""

    def __post_init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", self.supabase_url)
        self.supabase_key = os.getenv("SUPABASE_KEY", self.supabase_key)
        self.redis_url = os.getenv("UPSTASH_REDIS_URL", self.redis_url)
        self.redis_token = os.getenv("UPSTASH_REDIS_TOKEN", self.redis_token)

    def validate(self) -> bool:
        return bool(self.supabase_url and self.supabase_key) or bool(self.redis_url)


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    def __post_init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", self.bot_token)
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", self.chat_id)

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

    def __post_init__(self):
        self.max_daily_loss_pct = float(
            os.getenv("MAX_DAILY_LOSS_PCT", str(self.max_daily_loss_pct))
        )
        self.max_leverage = int(os.getenv("MAX_LEVERAGE", str(self.max_leverage)))
        self.default_sl_pct = float(
            os.getenv("DEFAULT_SL_PCT", str(self.default_sl_pct))
        )
        self.tp1_pct = float(os.getenv("TP1_PCT", str(self.tp1_pct)))
        self.tp2_pct = float(os.getenv("TP2_PCT", str(self.tp2_pct)))
        self.compounding_rate = float(
            os.getenv("COMPOUNDING_RATE", str(self.compounding_rate))
        )
        self.max_position_pct = float(
            os.getenv("MAX_POSITION_PCT", str(self.max_position_pct))
        )


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

    def __post_init__(self):
        symbols_env = os.getenv("TRADING_SYMBOLS", "")
        if symbols_env:
            self.symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]

        self.timeframe = os.getenv("TRADING_TIMEFRAME", self.timeframe)
        self.min_confidence_sniper = float(
            os.getenv("MIN_CONFIDENCE_SNIPER", str(self.min_confidence_sniper))
        )
        self.min_confidence_hunter = float(
            os.getenv("MIN_CONFIDENCE_HUNTER", str(self.min_confidence_hunter))
        )
        self.min_confidence_farmer = float(
            os.getenv("MIN_CONFIDENCE_FARMER", str(self.min_confidence_farmer))
        )
        self.leverage_sniper = int(
            os.getenv("LEVERAGE_SNIPER", str(self.leverage_sniper))
        )
        self.leverage_hunter = int(
            os.getenv("LEVERAGE_HUNTER", str(self.leverage_hunter))
        )
        self.leverage_farmer = int(
            os.getenv("LEVERAGE_FARMER", str(self.leverage_farmer))
        )


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
