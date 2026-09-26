# bot/main.py - Binance Testnet polling trader

import asyncio
import logging
import os
import time
from datetime import datetime, timezone


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

        self.state_manager = StateManager(self.config)
        self.telegram = TelegramNotifier()
        # ✅ تتبع الحالة المالية اليومية
        self._daily_loss_used = 0.0
        self._daily_realized_pnl = 0.0
        self._current_balance = 0.0

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
                    if balance <= 0:
                        raise RuntimeError("invalid or unavailable exchange balance")
                    self._current_balance = balance
                    self._daily_loss_limit = (
                        float(self.config.risk.max_daily_loss_pct or 4.0) / 100.0
                    ) * balance
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

        # ✅ فحص اتصال Supabase - إذا فشل، نكتب في واجهة مستقلة
        balance = await self.exchange.get_balance()
        if balance <= 0:
            raise RuntimeError("cannot initialize without a valid exchange balance")
        self._current_balance = balance
        self._daily_loss_limit = (
            float(self.config.risk.max_daily_loss_pct or 4.0) / 100.0
            * balance
        )

        # كتابة الحالة الأولية
        await self.state_manager.update_bot_status(
            balance=balance,
            daily_loss_used=self._daily_loss_used,
            daily_realized_pnl=self._daily_realized_pnl,
            daily_loss_limit=self._daily_loss_limit,
        )

        if self.state_manager.client is None:
            raise RuntimeError("Supabase is required for safe state persistence")

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
                current_price = float(ticker.get("last") or 0.0)
                if current_price <= 0:
                    logger.warning("Skipping %s: exchange returned no valid ticker", symbol)
                    continue

                # 2. إدارة المراكز المفتوحة
                open_positions = self.state_manager.get_open_trades_from_db()
                symbol_positions = [
                    p for p in open_positions if p.get("symbol") == symbol
                ]

                for pos in symbol_positions:
                    pos_obj = self.state_manager.reconstruct_position(pos)
                    if pos_obj is None:
                        continue

                    # ✅ إصلاح خلل حرج (مؤكَّد): pos_obj لم يكن يُسجَّل أبداً في
                    # PositionManager._positions، لذا كانت update_price() ترجع
                    # None دائماً لأي مركز مُستعاد من قاعدة البيانات — أي أن
                    # وقف الخسارة/جني الأرباح الجزئي/Trailing Stop المُدار
                    # داخلياً لم يكن يعمل إطلاقاً لأي صفقة قائمة بالفعل.
                    if self.position_manager.get_position(pos_obj.id) is None:
                        self.position_manager.add_position(pos_obj)

                    action = self.position_manager.update_price(
                        pos_obj.id, current_price
                    )

                    if action and action.get("action") == "partial_close":
                        # ✅ إصلاح: partial_close لم تكن تُعالَج إطلاقاً من قبل —
                        # كانت تُطلق من PositionManager وتُهمَل بصمت في main.py.
                        pct = action.get("percentage", 50)
                        logger.info(
                            f"🎯 TP1 وصل لـ {symbol} — إغلاق جزئي مطلوب ({pct}%)"
                        )
                        try:
                            partial_amount = (pos_obj.size_usd * pos_obj.leverage / current_price) * (pct / 100.0)
                            await self.exchange.reduce_only_close(
                                symbol=symbol,
                                amount=partial_amount,
                                reason="tp1",
                            )
                        except Exception as partial_err:
                            logger.error(f"❌ فشل تنفيذ الإغلاق الجزئي (TP1) لـ {symbol}: {partial_err}")
                        else:
                            if not self.state_manager.save_trade_state({**pos, "tp1_executed": True}):
                                raise RuntimeError("partial close executed but state persistence failed")
                            await self.telegram.send_partial_close(
                                pos_obj, current_price, pct,
                                partial_pnl=(current_price - pos_obj.entry_price) * pos_obj.size_usd * pos_obj.leverage / pos_obj.entry_price
                                if pos_obj.direction.value == "LONG" else
                                (pos_obj.entry_price - current_price) * pos_obj.size_usd * pos_obj.leverage / pos_obj.entry_price,
                            )

                    elif action and action.get("action") == "close":
                        order = await self.exchange.close_position(
                            symbol=symbol,
                            position_id=pos_obj.id,
                            reason=action.get("reason", "unknown"),
                            price=current_price
                        )

                        # ✅ إصلاح خلل حرج (مؤكَّد): close_position() في
                        # PositionManager (الذي يحسب pnl الفعلي) لم يكن يُستدعى
                        # أبداً — النتيجة: pnl محفوظ دائماً = 0 في القاعدة
                        # وفي إشعار Telegram، و_daily_realized_pnl/_daily_loss_used
                        # لا يتحدّثان أبداً، ما يجعل "حد الخسارة اليومي" مجرد رقم
                        # عرض بلا أي تفعيل فعلي.
                        closed_pos = self.position_manager.close_position(
                            pos_obj.id, current_price, action.get("reason", "manual")
                        )
                        realized_pnl = closed_pos.pnl if closed_pos else 0.0

                        self._daily_realized_pnl += realized_pnl
                        if realized_pnl < 0:
                            self._daily_loss_used += abs(realized_pnl)

                        self.state_manager.save_trade_state({
                            **pos,
                            "status": "CLOSED",
                            "exit_price": current_price,
                            "close_reason": action.get("reason"),
                            "pnl": realized_pnl,
                            "pnl_pct": closed_pos.pnl_pct if closed_pos else 0.0,
                            # ✅ إصلاح: عمود "duration_minutes" مطلوب من App.jsx
                            # ولم يكن يُحفَظ أبداً — Position.duration_minutes
                            # موجودة كخاصية محسوبة لكنها لم تُصدَّر لقاعدة البيانات.
                            "duration_minutes": round(closed_pos.duration_minutes, 2) if closed_pos else None,
                            "closed_at": datetime.now(timezone.utc).isoformat()
                        })
                        if closed_pos:
                            closed_pos.pnl = realized_pnl
                        await self.telegram.send_trade_closed(
                            closed_pos or pos_obj, action.get("reason", "")
                        )

                # ✅ إصلاح خلل حرج (مؤكَّد): تفعيل فعلي لحد الخسارة اليومي —
                # لم يكن موجوداً في أي مكان بالكود سابقاً رغم حساب الحد.
                if self._daily_loss_used >= getattr(self, "_daily_loss_limit", float("inf")):
                    logger.warning(
                        f"🛑 تم بلوغ حد الخسارة اليومي ({self._daily_loss_used:.2f}$ / "
                        f"{self._daily_loss_limit:.2f}$) — إيقاف فتح صفقات جديدة لبقية اليوم على {symbol}"
                    )
                    continue

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
                if balance <= 0:
                    logger.error("Skipping new entry for %s: balance unavailable", symbol)
                    continue
                self._current_balance = balance
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
                    take_profit=take_profit_1,
                    leverage=leverage,
                    client_order_id=f"apex-{symbol.replace('/', '')}-{int(time.time() * 1000)}",
                )

                # 6. حفظ الصفقة
                fee_result = self.fee_calculator.calculate(
                    position_size=size_usd * leverage
                )
                trade_record = {
                    "id": order.get("id", ""),
                    "symbol": symbol,
                    "direction": str(action_val).upper(),
                    # ✅ إصلاح: عمود "mode" مطلوب من App.jsx (لوحة المتابعة) في
                    # استعلام SELECT الخاص بجدول trades ولم يكن يُحفَظ أبداً —
                    # كان سيسبب فراغاً دائماً في هذا العمود بالواجهة.
                    "mode": str(self.config.active_mode),
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
                if not self.state_manager.save_trade_state(trade_record):
                    raise RuntimeError("order executed but trade state could not be persisted")
                logger.info(f"✅ صفقة جديدة: {symbol} {side} @ {entry_price}")

            except Exception as e:
                logger.error(f"❌ خطأ في {symbol}: {e}", exc_info=True)
                await self.telegram.send_error(f"Cycle Error [{symbol}]: {str(e)}")

    def _calculate_position_size(self) -> float:
        """حساب حجم الصفقة بناءً على الرصيد وإعدادات المخاطر."""
        try:
            initial = float(self._current_balance)
            if initial <= 0:
                raise ValueError("balance unavailable")
            pct = self.config.risk.max_position_pct / 100
            return round(initial * pct, 2)
        except Exception:
            return 10.0

    async def run_forever(self, interval_seconds: int = 60) -> None:
        """Run direct exchange polling and the real heartbeat loop."""
        max_cycles = int(os.environ.get("APEX_RUN_CYCLES", 0) or 0)
        single_cycle = max_cycles > 0

        await self.initialize()
        heartbeat_task = asyncio.create_task(
            self.start_heartbeat_loop(interval_seconds=10)
        )

        try:
            cycles_done = 0
            while True:
                await self.process_market_cycle()
                cycles_done += 1
                if single_cycle and cycles_done >= max_cycles:
                    logger.info(f"✅ اكتمل {max_cycles} دورة(ات) — خروج من APEX_RUN_CYCLES={max_cycles}")
                    break
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            # ✅ كتابة حالة الخروج واجبة — تضمن ظهور البيانات حتى في الدورة الواحدة
            await self.state_manager.update_heartbeat()
            await self.state_manager.mark_bot_stopped()
            await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Shutdown...")
        try:
            await self.state_manager.mark_bot_stopped()
        except Exception:
            pass
        # ✅ إغلاق موارد الـ exchange لتجنب تحذير unclosed connector
        try:
            await self.exchange.close()
        except Exception:
            pass
        try:
            await self.market_data.close()
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
            raise

    asyncio.run(_main())
