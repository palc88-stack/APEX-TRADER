import sys

checks = [
    ("bot.main ↔ bot.config",
     "from bot.main import ApexTraderBot; from bot.config import Config; b = ApexTraderBot(); assert isinstance(b.config, Config)"),
    ("bot.main ↔ market_data",
     "from bot.main import ApexTraderBot; from bot.data.market_data import MarketDataManager; b = ApexTraderBot(); assert isinstance(b.market_data, MarketDataManager)"),
    ("bot.main ↔ exchange",
     "from bot.main import ApexTraderBot; from bot.core.exchange import ExchangeManager; b = ApexTraderBot(); assert isinstance(b.exchange, ExchangeManager)"),
    ("bot.main ↔ signal_engine",
     "from bot.main import ApexTraderBot; from bot.signals.signal_engine import SignalEngine; b = ApexTraderBot(); assert isinstance(b.signal_engine, SignalEngine)"),
    ("bot.main ↔ indicators",
     "from bot.main import ApexTraderBot; from bot.signals.indicators import IndicatorCalculator; b = ApexTraderBot(); assert isinstance(b.indicators, IndicatorCalculator)"),
    ("bot.main ↔ risk_manager",
     "from bot.main import ApexTraderBot; from bot.core.risk_manager import RiskManager; b = ApexTraderBot(); assert isinstance(b.risk_manager, RiskManager)"),
    ("bot.main ↔ fee_calculator",
     "from bot.main import ApexTraderBot; from bot.core.fee_calculator import FeeCalculator; b = ApexTraderBot(); assert isinstance(b.fee_calculator, FeeCalculator)"),
    ("bot.main ↔ position_manager",
     "from bot.main import ApexTraderBot; from bot.core.position_manager import PositionManager; b = ApexTraderBot(); assert isinstance(b.position_manager, PositionManager)"),
    ("bot.main ↔ state_manager",
     "from bot.main import ApexTraderBot; from bot.data.state_manager import StateManager; b = ApexTraderBot(); assert isinstance(b.state_manager, StateManager)"),
    ("bot.main ↔ telegram",
     "from bot.main import ApexTraderBot; from bot.notifications.telegram_notifier import TelegramNotifier; b = ApexTraderBot(); assert isinstance(b.telegram, TelegramNotifier)"),
    ("bot.main ↔ supabase_client",
     "from bot.main import ApexTraderBot; from supabase import Client; b = ApexTraderBot(); assert isinstance(b.supabase_client, Client)"),
    ("signal_engine ↔ TradeSignal",
     "from bot.signals.signal_engine import SignalEngine, TradeSignal, TradeDirection; assert TradeSignal is not None"),
    ("indicators ↔ calculate_all",
     "from bot.signals.indicators import IndicatorCalculator; import pandas as pd; calc = IndicatorCalculator({}); df = pd.DataFrame({'close': [1,2,3], 'high': [1,2,3], 'low': [1,2,3], 'open': [1,2,3], 'volume': [1,2,3]}); result = calc.calculate_all(df); assert result is not None"),
    ("fee_calculator ↔ calculate",
     "from bot.core.fee_calculator import FeeCalculator; calc = FeeCalculator('binance'); r = calc.calculate(1000.0, 'taker', 'taker'); assert r.total_fee > 0"),
    ("fee_calculator ↔ adjust_targets",
     "from bot.core.fee_calculator import FeeCalculator; calc = FeeCalculator('binance'); t = calc.adjust_targets(43000, 'long', 0.25, 0.41, 0.71, 1000); assert 'stop_loss' in t"),
    ("risk_manager ↔ check_risk_limits",
     "from bot.core.risk_manager import RiskManager; from bot.signals.signal_engine import TradeSignal, TradeDirection; rm = RiskManager({}); sig = TradeSignal(symbol='BTC/USDT', action=TradeDirection.LONG, price=50000, confidence=0.85, strategy='T', reason='test'); assert rm.check_risk_limits(sig) in (True, False)"),
    ("risk_manager ↔ evaluate_risk",
     "from bot.core.risk_manager import RiskManager; rm = RiskManager({}); assert rm.evaluate_risk(100, 10, 10, 43000, 42892.5, 'buy') in (True, False)"),
    ("position_manager ↔ Position",
     "from bot.core.position_manager import PositionManager, Position; from bot.signals.signal_engine import TradeDirection; pm = PositionManager(); p = Position(id='t', symbol='BTC/USDT', direction=TradeDirection.LONG, exchange='binance', entry_price=43000, current_price=43000, stop_loss=42892.5, take_profit_1=43176.3, take_profit_2=43306.1, size_usd=10, leverage=10); pm.add_position(p); assert pm.get_position('t') is not None"),
    ("position_manager ↔ update_price",
     "from bot.core.position_manager import PositionManager, Position; from bot.signals.signal_engine import TradeDirection; import uuid; pm = PositionManager(); pos = Position(id=str(uuid.uuid4())[:8], symbol='BTC/USDT', direction=TradeDirection.LONG, exchange='binance', entry_price=43000, current_price=43000, stop_loss=42892.5, take_profit_1=43176.3, take_profit_2=43306.1, size_usd=10, leverage=10); pm.add_position(pos); pos_id = pos.id; pm.update_price(pos_id, 43064.5, atr=50.0); up = pm.get_position(pos_id); assert up is not None"),
    ("config ↔ enabled_exchanges",
     "from bot.config import ExchangeConfig; ec = ExchangeConfig(); ex = ec.enabled_exchanges(); assert isinstance(ex, list) and len(ex) > 0"),
    ("config ↔ primary_exchange",
     "from bot.config import ExchangeConfig; ec = ExchangeConfig(); assert ec.primary_exchange() in ('binance', 'bybit')"),
    ("config ↔ active_mode",
     "from bot.config import Config; c = Config(); assert c.active_mode in ('HUNTER', 'SCALP', 'STARTER', 'BOTH')"),
    ("config ↔ get method",
     "from bot.config import Config; c = Config(); assert callable(c.get); val = c.get('NONEXISTENT_KEY_XYZ'); assert val == ''"),
    ("config ↔ get_bool method",
     "from bot.config import Config; c = Config(); assert callable(c.get_bool); val = c.get_bool('NONEXISTENT_KEY_XYZ', False); assert val == False"),
    ("config ↔ nested exchange",
     "from bot.config import Config; c = Config(); assert hasattr(c, 'exchange'); assert c.exchange.binance_testnet in (True, False)"),
    ("config ↔ nested database",
     "from bot.config import Config; c = Config(); assert hasattr(c, 'database'); assert isinstance(c.database.supabase_url, str)"),
    ("config ↔ nested telegram",
     "from bot.config import Config; c = Config(); assert hasattr(c, 'telegram'); assert isinstance(c.telegram.bot_token, str)"),
    ("config ↔ nested risk",
     "from bot.config import Config; c = Config(); assert hasattr(c, 'risk'); assert c.risk.min_confidence > 0"),
    ("config ↔ nested trading",
     "from bot.config import Config; c = Config(); assert hasattr(c, 'trading'); assert len(c.trading.symbols) > 0"),
]

print("=" * 60)
print("تحقق تكامل الواجهات بين جميع الموديولات")
print("=" * 60)

passed = 0
failed = 0
for desc, code in checks:
    try:
        exec(code)
        print(f"  PASS  {desc}")
        passed += 1
    except Exception as e:
        print(f"  FAIL  {desc}")
        print(f"         السبب: {e}")
        failed += 1

print("=" * 60)
print(f"المجموع: {passed} نجح، {failed} فشل")
if failed == 0:
    print("النظام INTEGRATED — جميع الواجهات متوافقة ومربطة")
else:
    print(f"⚠️ ما زال هناك {failed} مشكلة تحتاج إصلاحاً")
