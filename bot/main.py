# bot/main.py - الكود المُصحَّح (كامل + Webhook Endpoint)

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import aiohttp
from aiohttp import web
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

        self.exchange = ExchangeManager(self.config)
        self.market_data = MarketDataManager(exchange_source=self.exchange)

        self.indicators = IndicatorCalculator(self.config)
        self.filters = SignalFilters(self.config)
        self.explosion_detector = ExplosionDetector()
        self.scalping_strategy = ScalpingStrategy(self.config)
        self.signal_engine = SignalEngine(self.config)

        self.risk_manager = RiskManager(self.config)
        self.fee_calculator = FeeCalculator(self.config)
        self.position_manager = PositionManager()

        self.supabase_client: Client = self._init_supabase()
        self.state_manager = StateManager(self.config)
        self.telegram = TelegramNotifier()
        # ✅ تتبع الحالة المالية اليومية
        self._daily_loss_used = 0.0
        self._daily_realized_pnl = 0.0
        # ✅ Webhook server
        self._webhook_runner: Optional[web.AppRunner] = None
        self._webhook_site: Optional[web.TCPSite] = None
        self._webhook_port: int = 8080

    def _init_supabase(self) -> Client:
        try:
            client = create_client(
                self.config.database.supabase_url,
                self.config.database.supabase_key
            )
            logger.info("✅ Supabase client initialized")
            return client
        except Exception as e:
            logger.warning(f"⚠️ Supabase init failed (no valid keys): {e}")
            return None

    # ✅ إصلاح: Heartbeat عبر StateManager
    async def start_heartbeat_loop(self, interval_seconds: int = 10):
        """إرسال نبضات دورية عبر StateManager - لا كتابة مباشرة لـ Supabase."""
        logger.info("💗 بدء حلقة Heartbeat...")
        while True:
            try:
                await self.state_manager.update_heartbeat()
                # ✅ تحديث الحالة المالية كل دورة
                try:
                    balance = await self.exchange.get_balance()
                    self._daily_loss_limit = (
                        float(self.config.risk.max_daily_loss_pct or 0.02)
                        * balance
                    )
                    await self.state_manager.update_bot_status(
                        balance=balance,
                        daily_loss_used=self._daily_loss_used,
                        daily_realized_pnl=self._daily_realized_pnl,
                        daily_loss_limit=self._daily_loss_limit,
                    )
                except Exception as e:
                    logger.debug(f"⚠️ لا يمكن جلب الرصيد للـ heartbeat: {e}")
            except Exception as e:
                logger.error(f"⚠️ فشل Heartbeat: {e}")
            await asyncio.sleep(interval_seconds)

    async def initialize(self) -> None:
        logger.info("Initializing ApexTrader...")
        await self.state_manager.load_initial_state()
        balance = await self.exchange.get_balance()
        self._daily_loss_limit = (
            float(self.config.risk.max_daily_loss_pct or 0.02)
            * balance
        )
        await self.state_manager.update_bot_status(
            balance=balance,
            daily_loss_used=self._daily_loss_used,
            daily_realized_pnl=self._daily_realized_pnl,
            daily_loss_limit=self._daily_loss_limit,
        )
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
        """استقبال إشارات Webhook (TradingView) وتنفيذها فوراً"""
        symbol = webhook_data.get("symbol", "")
        side = webhook_data.get("side", "").lower()
        action = webhook_data.get("action", "").upper()
        price = float(webhook_data.get("price", 0))
        webhook_id = webhook_data.get("id", "")

        logger.info(f"📥 Webhook Signal: {symbol} {side} @ {price} (id={webhook_id})")

        # توحيد الاتجاه
        if side == "buy" or action in ("BUY", "LONG"):
            order_side = "buy"
            direction = "LONG"
        else:
            order_side = "sell"
            direction = "SHORT"

        # 1. التحقق من المراكز المفتوحة
        open_positions = self.state_manager.get_open_trades_from_db()
        symbol_positions = [p for p in open_positions if p.get("symbol") == symbol]

        if symbol_positions:
            logger.warning(f"⚠️ يوجد مركز مفتوح بالفعل على {symbol} — تم تجاوز الإشارة")
            return

        # 2. فحص المخاطر (الثقة والحدود)
        fake_signal = type("S", (), {
            "symbol": symbol,
            "action": direction,
            "confidence": 0.85,
            "price": price,
        })()

        if not self.risk_manager.check_risk_limits(
            fake_signal,
            open_positions=symbol_positions
        ):
            logger.warning(f"⚠️ risk_manager رفض الإشارة لـ {symbol}")
            return

        # 3. جلب السعر الحالي
        if price <= 0:
            ticker = await self.exchange.get_ticker(symbol)
            current_price = float(ticker.get("last", 0))
        else:
            current_price = price

        if current_price <= 0:
            logger.error(f"❌ سعر غير صالح لـ {symbol}: {current_price}")
            return

        # 4. حساب الأسعار
        risk_cfg = self.config.risk
        sl_pct = risk_cfg.default_sl_pct / 100
        tp1_pct = risk_cfg.tp1_pct / 100
        tp2_pct = risk_cfg.tp2_pct / 100
        leverage = risk_cfg.max_leverage
        size_usd = self._calculate_position_size()

        if order_side == "buy":
            stop_loss = round(current_price * (1 - sl_pct), 6)
            take_profit_1 = round(current_price * (1 + tp1_pct), 6)
            take_profit_2 = round(current_price * (1 + tp2_pct), 6)
        else:
            stop_loss = round(current_price * (1 + sl_pct), 6)
            take_profit_1 = round(current_price * (1 - tp1_pct), 6)
            take_profit_2 = round(current_price * (1 - tp2_pct), 6)

        # 5. فحص المخاطر المتقدمة
        balance = await self.exchange.get_balance()
        if not self.risk_manager.evaluate_risk(
            account_balance=balance,
            size_usd=size_usd,
            leverage=leverage,
            entry_price=current_price,
            stop_loss=stop_loss,
            direction=order_side
        ):
            logger.warning(f"⚠️ evaluate_risk رفض لـ {symbol}")
            return

        # 6. تنفيذ الأمر
        order = await self.exchange.place_order(
            symbol=symbol,
            side=order_side,
            amount=size_usd / current_price,
            price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit_1
        )

        # 7. حفظ الصفقة
        fee_result = self.fee_calculator.calculate(
            position_size=size_usd * leverage
        )
        trade_record = {
            "id": str(order.get("id", "") or webhook_id or f"web-{int(time.time())}"),
            "symbol": symbol,
            "direction": direction,
            "exchange": self.config.exchange.primary_exchange(),
            "entry_price": current_price,
            "stop_loss": stop_loss,
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "size_usd": size_usd,
            "leverage": leverage,
            "entry_fee": fee_result.entry_fee,
            "exit_fee": fee_result.exit_fee,
            "status": "OPEN",
            "confidence": 0.85,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "tp1_executed": False,
            "trailing_active": False,
            "trailing_stop": 0,
            "breakeven_set": False,
            "highest_price": current_price,
            "lowest_price": current_price,
            "source": "webhook",
        }
        self.state_manager.save_trade_state(trade_record)
        logger.info(f"✅ صفقة من.Webhook: {symbol} {order_side} @ {current_price} | ID: {trade_record['id']}")

    # ── Webhook Server ──────────────────────────────────────────────────────────

    async def start_webhook_server(self) -> None:
        """بدء خادم webhook internal لاستقبال الإشارات من worker.js/TradingView"""
        app = web.Application()
        app.router.add_post('/webhook', self._webhook_handler)
        self._webhook_runner = web.AppRunner(app)
        await self._webhook_runner.setup()
        self._webhook_site = web.TCPSite(self._webhook_runner, '0.0.0.0', self._webhook_port)
        await self._webhook_site.start()
        logger.info(f"🌐 Webhook server listening on port {self._webhook_port} (path: /webhook)")

    async def stop_webhook_server(self) -> None:
        """إيقاف خادم webhook"""
        if self._webhook_site:
            await self._webhook_site.stop()
        if self._webhook_runner:
            await self._webhook_runner.cleanup()
        logger.info("🛑 Webhook server stopped")

    async def _webhook_handler(self, request: web.Request) -> web.Response:
        """استقبال إشارات من worker.js (TradingView)"""
        # 1. التحقق من المصادقة
        auth_header = request.headers.get('Authorization', '')
        expected_auth = f"Bearer {self.config.webhook.internal_api_key}"
        if not self.config.webhook.internal_api_key:
            logger.warning("⚠️ INTERNAL_API_KEY غير مضبوط — الـ webhook مرفوض")
            return web.json_response({"error": "Server not configured"}, status=503)
        if auth_header != expected_auth:
            logger.warning("⚠️ محاولة وصول غير مصرح بها إلى webhook")
            return web.json_response({"error": "Unauthorized"}, status=401)

        # 2. قراءة البيانات
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        # 3. التحقق من صحة الإشارة
        symbol = data.get("symbol", "")
        side = data.get("side", "").lower()
        action = data.get("action", "").upper()

        if not symbol or side not in ("buy", "sell") or action not in ("BUY", "SELL", "LONG", "SHORT"):
            logger.warning(f"⚠️ إشارة غير صالحة: {data}")
            return web.json_response({"error": "Invalid signal format"}, status=400)

        # 4. معالجة الإشارة
        try:
            await self.handle_webhook_signal(data)
            return web.json_response({"success": True, "message": f"Signal processed for {symbol}"})
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة الـ webhook: {e}", exc_info=True)
            return web.json_response({"error": "Processing failed"}, status=500)

    async def run_forever(self, interval_seconds: int = 60) -> None:
        # ✅ بدء webhook server قبل حلقة التداول
        await self.start_webhook_server()
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
            await self.stop_webhook_server()
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