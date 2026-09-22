# ======================================
# APEX TRADER - Configuration Manager
# ======================================
# المسؤول عن إدارة جميع إعدادات البوت
# بطريقة آمنة ومنظمة

import os
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv
from loguru import logger

# تحميل متغيرات البيئة
load_dotenv()


@dataclass
class ExchangeConfig:
    """إعدادات منصات التداول"""
    
    # Binance
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = True
    
    # Bybit
    bybit_api_key: str = ""
    bybit_secret_key: str = ""
    bybit_testnet: bool = True
    
    def __post_init__(self):
        """تحميل المفاتيح من متغيرات البيئة"""
        self.binance_api_key = os.getenv("BINANCE_API_KEY", "")
        self.binance_secret_key = os.getenv("BINANCE_SECRET_KEY", "")
        self.binance_testnet = os.getenv(
            "BINANCE_TESTNET", "true"
        ).lower() == "true"
        
        self.bybit_api_key = os.getenv("BYBIT_API_KEY", "")
        self.bybit_secret_key = os.getenv("BYBIT_SECRET_KEY", "")
        self.bybit_testnet = os.getenv(
            "BYBIT_TESTNET", "true"
        ).lower() == "true"
    
    def validate(self) -> bool:
        """التحقق من صحة الإعدادات"""
        if not self.binance_api_key or not self.binance_secret_key:
            logger.error("❌ Binance API keys مفقودة!")
            return False
        return True


@dataclass
class RiskConfig:
    """إعدادات إدارة المخاطر"""
    
    # حدود المخاطر
    max_daily_loss_pct: float = 4.0      # أقصى خسارة يومية %
    max_leverage: int = 20               # أقصى رافعة مالية
    max_position_pct: float = 20.0       # أقصى حجم صفقة %
    
    # إعدادات الصفقة
    default_sl_pct: float = 0.25        # وقف خسارة افتراضي %
    tp1_pct: float = 0.41              # هدف ربح 1 %
    tp2_pct: float = 0.71              # هدف ربح 2 %
    
    # Trailing Stop
    trailing_activation_pct: float = 0.15  # تفعيل Trailing %
    breakeven_pct: float = 0.15            # نقطة التعادل %
    
    # العمولات
    binance_maker_fee: float = 0.0002   # 0.02%
    binance_taker_fee: float = 0.0004   # 0.04%
    bybit_maker_fee: float = 0.0002     # 0.02%
    bybit_taker_fee: float = 0.00055    # 0.055%
    
    # Compounding
    compounding_rate: float = 0.70      # 70% إعادة استثمار
    
    def __post_init__(self):
        """تحميل من متغيرات البيئة"""
        self.max_daily_loss_pct = float(
            os.getenv("MAX_DAILY_LOSS_PCT", "4.0")
        )
        self.max_leverage = int(
            os.getenv("MAX_LEVERAGE", "20")
        )
        self.compounding_rate = float(
            os.getenv("COMPOUNDING_RATE", "0.70")
        )


@dataclass
class TradingConfig:
    """إعدادات التداول"""
    
    # العملات المدعومة
    symbols: List[str] = field(default_factory=lambda: [
        "BTC/USDT",
        "ETH/USDT", 
        "SOL/USDT",
        "XRP/USDT",
        "BNB/USDT"
    ])
    
    # الأوضاع
    active_mode: str = "HUNTER"         # SNIPER/HUNTER/FARMER
    
    # الإطارات الزمنية
    timeframe: str = "5m"               # الإطار الأساسي
    higher_timeframe: str = "1h"        # الإطار الأعلى
    
    # حدود الإشارة
    min_confidence_sniper: float = 0.90
    min_confidence_hunter: float = 0.70
    min_confidence_farmer: float = 0.55
    
    # الليفريج حسب الوضع
    leverage_sniper: int = 15
    leverage_hunter: int = 10
    leverage_farmer: int = 7
    
    def __post_init__(self):
        self.active_mode = os.getenv("ACTIVE_MODE", "HUNTER")


@dataclass 
class DatabaseConfig:
    """إعدادات قاعدة البيانات"""
    
    supabase_url: str = ""
    supabase_key: str = ""
    redis_url: str = ""
    redis_token: str = ""
    
    def __post_init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
        self.redis_url = os.getenv("UPSTASH_REDIS_URL", "")
        self.redis_token = os.getenv("UPSTASH_REDIS_TOKEN", "")
    
    def validate(self) -> bool:
        """التحقق من صحة الإعدادات"""
        if not self.supabase_url or not self.supabase_key:
            logger.warning("⚠️ Supabase غير مضبوط - التداول بدون DB")
            return False
        return True


@dataclass
class TelegramConfig:
    """إعدادات Telegram"""
    
    bot_token: str = ""
    chat_id: str = ""
    
    def __post_init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    
    def validate(self) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.warning("⚠️ Telegram غير مضبوط")
            return False
        return True


class Config:
    """الإعداد المركزي للبوت"""
    
    _instance: Optional['Config'] = None
    
    def __new__(cls) -> 'Config':
        """Singleton Pattern - نسخة واحدة فقط"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
            
        self.exchange = ExchangeConfig()
        self.risk = RiskConfig()
        self.trading = TradingConfig()
        self.database = DatabaseConfig()
        self.telegram = TelegramConfig()
        
        # بيئة التشغيل
        self.environment = os.getenv("ENVIRONMENT", "testnet")
        self.initial_balance = float(
            os.getenv("INITIAL_BALANCE", "100")
        )
        
        self._initialized = True
        logger.info("✅ Config محملة بنجاح")
    
    @property
    def is_testnet(self) -> bool:
        """هل نعمل على Testnet؟"""
        return self.environment == "testnet"
    
    @property
    def is_production(self) -> bool:
        """هل نعمل على الإنتاج؟"""
        return self.environment == "production"
    
    def validate_all(self) -> bool:
        """التحقق من جميع الإعدادات"""
        exchange_ok = self.exchange.validate()
        
        if not exchange_ok:
            logger.error("❌ فشل التحقق من إعدادات المنصة!")
            return False
        
        logger.info("✅ جميع الإعدادات صحيحة")
        return True


# نسخة عامة للاستخدام
config = Config()
