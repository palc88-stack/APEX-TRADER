import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import redis.asyncio as aioredis
from supabase import create_client, Client

from bot.config import Config
from bot.data.market_data import MarketDataFeed
from bot.core.exchange import ExchangeAdapter
from bot.signals.signal_engine import SignalEngine
from bot.signals.indicators import IndicatorCalculator
from bot.signals.filters import SignalFilter
from bot.strategies.explosion import ExplosionStrategy
from bot.strategies.scalping import ScalpingStrategy
from bot.core.risk_manager import RiskManager
from bot.core.fee_calculator import FeeCalculator
from bot.core.position_manager import PositionManager
from bot.data.state_manager import StateManager
from bot.notifications.telegram_notifier import TelegramNotifier

logger = logging.getLogger("ApexTrader.Main")

class ApexTraderBot:
    def __init__(self):
        self.config = Config()
        
        # Runtime & Exchange Connections
        self.market_data = MarketDataFeed(self.config)
        self.exchange = ExchangeAdapter(self.config)
        
        # Analysis & Signal Pipeline
        self.indicators = IndicatorCalculator(self.config)
        self.filters = SignalFilter(self.config)
        self.explosion_strategy = ExplosionStrategy(self.config)
        self.scalping_strategy = ScalpingStrategy(self.config)
        self.signal_engine = SignalEngine(
            config=self.config,
            indicators=self.indicators,
            filters=self.filters,
            explosion=self.explosion_strategy,
            scalping=self.scalping_strategy
        )
        
        # Risk & Position Controls
        self.risk_manager = RiskManager(self.config)
        self.fee_calculator = FeeCalculator(self.config)
        self.position_manager = PositionManager(self.config)
        
        # Persistence Layer (Redis Cache + Supabase Storage)
        self.redis_client = aioredis.from_url(self.config.REDIS_URL, decode_responses=True)
        self.supabase_client: Client = create_client(self.config.SUPABASE_URL, self.config.SUPABASE_KEY)
        self.state_manager = StateManager(
            redis=self.redis_client,
            supabase=self.supabase_client
        )
        
        # Telegram Notification Channel
        self.telegram = TelegramNotifier(
            bot_token=self.config.TELEGRAM_BOT_TOKEN,
            chat_id=self.config.TELEGRAM_CHAT_ID
        )

    async def start_heartbeat_loop(self, interval_seconds: int = 10):
        """إرسال نبضات دورية حية لتحديث حالة الخدمات في الواجهة."""
        logger.info("💗 تم بدء حلقة إرسال النبضات الحية (Heartbeat)...")
        while True:
            try:
                now_utc = datetime.now(timezone.utc).isoformat()
                self.supabase_client.table("bot_runtime_status").upsert({
                    "id": 1,
                    "is_running": True,
                    "last_heartbeat": now_utc,
                    "updated_at": now_utc
                }).execute()
                logger.debug(f"💓 Heartbeat updated: {now_utc}")
            except Exception as e:
                logger.error(f"⚠️ فشل تحديث النبضة: {e}")
            await asyncio.sleep(interval_seconds)

    async def initialize(self) -> None:
        """تهيئة الاتصالات واستعادة الحالة السابقة من Supabase/Redis."""
        logger.info("Initializing ApexTrader runtime environment...")
        await self.state_manager.load_initial_state()
        await self.telegram.send_message("🤖 **ApexTrader Engine Started Successfully**")

    async def process_market_cycle(self) -> None:
        """دورة تحليل وتداول واستجابة فورية لتغيرات السوق."""
        logger.info(f"Running market execution cycle: {datetime.now(timezone.utc).isoformat()}")
        
        for symbol in self.config.trading.symbols:
            try:
                # 1. جلب بيانات الأسعار الحيّة
                candles = await self.market_data.get_candles(symbol, self.config.trading.timeframe)
                ticker = await self.exchange.get_ticker(symbol)
                current_price = ticker["close"]

                # 2. إدارة الصفقات المفتوحة
                active_positions = await self.state_manager.get_active_positions(symbol)
                for pos in active_positions:
                    pos_update = self.position_manager.evaluate_position(pos, current_price)
                    
                    if pos_update.should_close or pos_update.should_partial_close:
                        close_res = await self.exchange.close_position(
                            symbol=symbol,
                            position_id=pos["id"],
                            percentage=pos_update.close_percentage,
                            price=current_price
                        )
                        await self.state_manager.update_position(pos["id"], close_res)
                        await self.telegram.send_trade_update(symbol, close_res)

                # 3. معالجة وتوليد الإشارات الجديدة
                signal = await self.signal_engine.analyze(symbol, candles)
                
                if signal and signal.is_valid:
                    if self.risk_manager.check_risk_limits(signal):
                        adjusted_signal = self.fee_calculator.apply_fees(signal)
                        order = await self.exchange.place_order(
                            symbol=adjusted_signal.symbol,
                            side=adjusted_signal.side,
                            amount=adjusted_signal.amount,
                            price=adjusted_signal.price,
                            stop_loss=adjusted_signal.stop_loss,
                            take_profit=adjusted_signal.take_profit
                        )
                        await self.state_manager.save_position(order)
                        await self.telegram.send_trade_signal(adjusted_signal, order)
                    else:
                        logger.warning(f"Risk controls blocked trade for {symbol}")

            except Exception as e:
                logger.error(f"Error processing {symbol}: {str(e)}", exc_info=True)
                await self.telegram.send_error_alert(f"Cycle Error [{symbol}]: {str(e)}")

    async def handle_webhook_signal(self, webhook_data: Dict[str, Any]) -> None:
        """استقبال وتنفيد إشارات Webhook (TradingView -> worker.js)."""
        logger.info(f"Processing Webhook Signal for {webhook_data.get('symbol')}")
        parsed_signal = self.signal_engine.parse_external_signal(webhook_data)
        
        if parsed_signal and self.risk_manager.check_risk_limits(parsed_signal):
            order = await self.exchange.place_order_from_signal(parsed_signal)
            await self.state_manager.save_position(order)
            await self.telegram.send_trade_signal(parsed_signal, order)

    async def run_forever(self, interval_seconds: int = 60) -> None:
        """تشغيل البوت في حلقة مستمرة."""
        await self.initialize()
        
        # إطلاق حلقة النبضات كـ Background Task
        heartbeat_task = asyncio.create_task(self.start_heartbeat_loop(interval_seconds=10))
        
        try:
            while True:
                await self.process_market_cycle()
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Main loop cancelled, shutting down gracefully...")
        finally:
            heartbeat_task.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        """إغلاق الموارد وتحديث حالة إيقاف البوت."""
        logger.info("Closing exchange and persistence connections...")
        try:
            now_utc = datetime.now(timezone.utc).isoformat()
            self.supabase_client.table("bot_runtime_status").update({
                "is_running": False,
                "updated_at": now_utc
            }).eq("id", 1).execute()
        except Exception:
            pass
        
        await self.exchange.close()
        await self.market_data.close()
        await self.redis_client.close()
        await self.telegram.send_message("🛑 **ApexTrader Engine Shutdown Complete**")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    bot = ApexTraderBot()
    try:
        asyncio.run(bot.run_forever())
    except KeyboardInterrupt:
        logger.info("Engine stopped manually by operator.")
