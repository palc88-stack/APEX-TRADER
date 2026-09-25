# bot/config.py - إضافة TradingConfig والخصائص المفقودة
# أضف هذا في config.py بعد RiskConfig:

from typing import List

@dataclass
class TradingConfig:
    """✅ إعدادات التداول المفقودة"""
    symbols: List[str] = field(
        default_factory=lambda: ["BTC/USDT"]
    )
    timeframe: str = "5m"

    def __post_init__(self) -> None:
        raw_symbols = _env_text(
            "TRADING_SYMBOLS", "BTC/USDT"
        )
        self.symbols = [
            s.strip().upper()
            for s in raw_symbols.split(",")
            if s.strip()
        ] or ["BTC/USDT"]

        self.timeframe = _env_text(
            "TRADING_TIMEFRAME", self.timeframe
        )


@dataclass
class Config:
    """✅ الإعدادات الرئيسية المكتملة"""
    exchange: ExchangeConfig = field(
        default_factory=ExchangeConfig
    )
    database: DatabaseConfig = field(
        default_factory=DatabaseConfig
    )
    telegram: TelegramConfig = field(
        default_factory=TelegramConfig
    )
    risk: RiskConfig = field(
        default_factory=RiskConfig
    )
    trading: TradingConfig = field(      # ✅ مضاف
        default_factory=TradingConfig
    )

    # ✅ خصائص مفقودة من .env.example
    initial_balance: float = 100.0
    active_mode: str = "HUNTER"

    def __post_init__(self) -> None:
        self.initial_balance = _env_float(
            "INITIAL_BALANCE", self.initial_balance
        )
        self.active_mode = _env_text(
            "ACTIVE_MODE", self.active_mode
        ).upper()

# ✅ إضافة في .env.example:
# TRADING_SYMBOLS=BTC/USDT,ETH/USDT
# TRADING_TIMEFRAME=5m
