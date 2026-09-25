# bot/main.py - الكود المُصحَّح (كامل)

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import redis.asyncio as aioredis
from supabase import create_client, Client

from bot.config import Config
from bot.data.market_data import MarketDataManager
from bot.core.exchange import ExchangeManager
from bot.signals.signal_engine import SignalEngine
from bot.signals.indicators import IndicatorCalculator
from bot.signals.filters import SignalFilters
from bot.strategies.explosion import ExplosionDetector
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

        self.market_data = MarketDataManager()
        self.exchange = ExchangeManager(self.config)

        self.indicators = IndicatorCalculator(self.config)
        self.filters = SignalFilters(self.config)
        self.explosion_detector = ExplosionDetector()
        self.scalping_strategy = ScalpingStrategy(self.config)
        self.signal_engine = SignalEngine(self.config)

        self.risk_manager = RiskManager(self.config)
        self.fee_calculator = FeeCalculator(self.config)
        self.position_manager = PositionManager()

        self.supabase_client: Client = create_client(
            self.config.database.supabase_url,
            self.config.database.supabase_key
        )
        self.state_manager = StateManager(self.config)
        self.telegram = TelegramNotifier()

    # ✅ إصلاح: Heartbeat عبر StateManager + جدول صحيح (bot_state)
    async def start_heartbeat_loop(self, interval_seconds: int = 10):
        """إرسال نبضات دورية عبر StateManager - لا كتابة مباشرة لـ Supabase."""
        logger.info("💗 بدء حلقة Heartbeat...")
        while True:
            try:
                await self.state_manager.update_heartbeat()
            except Exception as e:
                logger.error(f"⚠️ فشل Heartbeat: {e}")
            await asyncio.sleep(interval_seconds)

    async def initialize(self) -> None:
        logger.info("Initializing ApexTrader...")
        await self.state_manager.load_initial_state()
        balance = await self.exchange.get_balance()
        await self.telegram.send_startup(
            balance=balance,
            mode=str(self.config.active_mode)
        )

    async def process_market_cycle(self) -> None:
        logger.info(f"Market cycle: {datetime.now(timezone.utc).isoformat()}")

        for symbol in self.config.trading.symbols:
            try:
                # 1. جلب البيانات
                candles = await self.market_data.get_ohlcv(
                    symbol, self.config.trading.timeframe
                )
                if candles is None or candles.empty:
                    continue

                ticker = await self.exchange.get_ticker(symbol)
                current_price = float(ticker["last"])

                # 2. إدارة المراكز المفتوحة
                open_positions = self.state_manager.get_open_trades_from_db()
                symbol_positions = [
                    p for p in open_positions if p.get("symbol") == symbol
                ]

                for pos in symbol_positions:
                    pos_obj = self.state_manager.reconstruct_position(pos)
                    if pos_obj is None:
                        continue

                    action = self.position_manager.update_price(
                        pos_obj.id, current_price
                    )
                    if action and action.get("action") == "close":
                        order = await self.exchange.close_position(
                            symbol=symbol,
                            position_id=pos_obj.id,
                            reason=action.get("reason", "unknown"),
                            price=current_price
                        )
                        self.state_manager.save_trade_state({
                            **pos,
                            "status": "CLOSED",
                            "exit_price": current_price,
                            "close_reason": action.get("reason"),
                            "closed_at": datetime.now(timezone.utc).isoformat()
                        })
                        await self.telegram.send_trade_closed(pos_obj, action.get("reason", ""))

                # 3. توليد إشارة جديدة
                df_with_indicators = self.indicators.calculate_all(candles)
                signal_result = self.signal_engine.evaluate_market(
                    df_with_indicators, symbol
                )

                from bot.signals.signal_engine import TradeDirection
                action_val = signal_result.get("action")
                if action_val in (TradeDirection.HOLD, "HOLD"):
                    continue

                # ✅ إصلاح: تمرير المراكز المفتوحة لـ RiskManager
                if not self.risk_manager.check_risk_limits(
                    type("S", (), signal_result)(),
                    open_positions=symbol_positions
                ):
                    continue

                # 4. حساب الأسعار وتنفيذ الأمر
                entry_price = current_price
                risk_cfg = self.config.risk
                sl_pct = risk_cfg.default_sl_pct / 100
                tp1_pct = risk_cfg.tp1_pct / 100
                tp2_pct = risk_cfg.tp2_pct / 100
                leverage = risk_cfg.max_leverage
                size_usd = self._calculate_position_size()

                if str(action_val).upper() in ("LONG", "BUY"):
                    stop_loss = round(entry_price * (1 - sl_pct), 6)
                    take_profit_1 = round(entry_price * (1 + tp1_pct), 6)
                    take_profit_2 = round(entry_price * (1 + tp2_pct), 6)
                    side = "buy"
                else:
                    stop_loss = round(entry_price * (1 + sl_pct), 6)
                    take_profit_1 = round(entry_price * (1 - tp1_pct), 6)
                    take_profit_2 = round(entry_price * (1 - tp2_pct), 6)
                    side = "sell"

                # ✅ تحقق evaluate_risk قبل التنفيذ
                balance = await self.exchange.get_balance()
                if not self.risk_manager.evaluate_risk(
                    account_balance=balance,
                    size_usd=size_usd,
                    leverage=leverage,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    direction=side
                ):
                    continue

                # 5. تنفيذ الأمر على البورصة
                order = await self.exchange.place_order(
                    symbol=symbol,
                    side=side,
                    amount=size_usd / entry_price,
                    price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit_1
                )

                # 6. حفظ الصفقة
                fee_result = self.fee_calculator.calculate(
                    position_size=size_usd * leverage
                )
                trade_record = {
                    "id": order.get("id", ""),
                    "symbol": symbol,
                    "direction": str(action_val).upper(),
                    "exchange": self.config.exchange.primary_exchange(),
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "take_profit_1": take_profit_1,
                    "take_profit_2": take_profit_2,
                    "size_usd": size_usd,
                    "leverage": leverage,
                    "entry_fee": fee_result.entry_fee,
                    "exit_fee": fee_result.exit_fee,
                    "status": "OPEN",
                    "confidence": signal_result.get("confidence", 0.0),
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "tp1_executed": False,
                    "trailing_active": False,
                    "trailing_stop": 0,
                    "breakeven_set": False,
                    "highest_price": entry_price,
                    "lowest_price": entry_price
                }
                self.state_manager.save_trade_state(trade_record)
                logger.info(f"✅ صفقة جديدة: {symbol} {side} @ {entry_price}")

            except Exception as e:
                logger.error(f"❌ خطأ في {symbol}: {e}", exc_info=True)
                await self.telegram.send_error(f"Cycle Error [{symbol}]: {str(e)}")

    def _calculate_position_size(self) -> float:
        """حساب حجم الصفقة بناءً على الرصيد وإعدادات المخاطر."""
        try:
            initial = float(self.config.initial_balance)
            pct = self.config.risk.max_position_pct / 100
            return round(initial * pct, 2)
        except Exception:
            return 10.0

    async def handle_webhook_signal(self, webhook_data: Dict[str, Any]) -> None:
        """استقبال إشارات Webhook (TradingView) بعد التحقق من التوقيع في worker.js."""
        symbol = webhook_data.get("symbol", "")
        logger.info(f"Webhook Signal: {symbol}")

        signal_result = self.signal_engine.evaluate_market(None, symbol)
        open_positions = self.state_manager.get_open_trades_from_db()
        symbol_positions = [p for p in open_positions if p.get("symbol") == symbol]

        if not self.risk_manager.check_risk_limits(
            type("S", (), signal_result)(),
            open_positions=symbol_positions
        ):
            return

        logger.info(f"✅ Webhook signal approved for {symbol}")

    async def run_forever(self, interval_seconds: int = 60) -> None:
        await self.initialize()
        heartbeat_task = asyncio.create_task(
            self.start_heartbeat_loop(interval_seconds=10)
        )
        try:
            while True:
                await self.process_market_cycle()
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            heartbeat_task.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Shutdown...")
        try:
            await self.state_manager.mark_bot_stopped()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — يُستدعى عند `python -m bot.main`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import sys

    # إعادة توجيه loguru إلى stdout حتى تظهر في سجلات الـ workflow
    from loguru import logger as _logger
    _logger.remove()
    _logger.add(
        sys.stdout,
        format="<level>{level}</level> | {message}",
        level=0,
        colorize=False,
    )

    async def _main():
        _logger.info("🚀 بدء تشغيل APEX TRADER...")
        bot = ApexTraderBot()
        try:
            await bot.run_forever(interval_seconds=60)
        except KeyboardInterrupt:
            _logger.info("⛔ توقف يدوياً")
        except Exception as e:
            _logger.error(f"❌ خطأ fatal: {e}", exc_info=True)

    asyncio.run(_main())
