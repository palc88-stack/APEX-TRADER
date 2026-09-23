# ======================================
# APEX TRADER - Main Bot Engine
# ======================================
# المحرك الرئيسي للبوت
# يجمع كل المكونات ويشغّلها

import asyncio
import uuid
import sys
from datetime import datetime
from typing import List
from loguru import logger

from bot.config import config
from bot.core.exchange import ExchangeManager
from bot.core.risk_manager import RiskManager
from bot.core.position_manager import PositionManager, Position
from bot.core.fee_calculator import FeeCalculator
from bot.signals.signal_engine import SignalEngine, TradeSignal
from bot.data.state_manager import StateManager
from bot.data.market_data import MarketDataManager
from bot.notifications.telegram_notifier import TelegramNotifier


logger.remove()
logger.add(
    sys.stdout,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO",
)
logger.add(
    "logs/apex_trader_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG",
)


class ApexTrader:
    VERSION = "1.0.0"

    def __init__(self):
        logger.info(f"🚀 تشغيل APEX TRADER v{self.VERSION}")

        if not config.validate_all():
            raise RuntimeError("❌ فشل تحميل الإعدادات!")

        self.exchange = ExchangeManager()
        self.risk_manager = RiskManager()
        self.position_manager = PositionManager()
        self.signal_engine = SignalEngine()
        self.fee_calculator = FeeCalculator()
        self.state_manager = StateManager()
        self.market_data = MarketDataManager()
        self.notifier = TelegramNotifier()

        self._running = False
        self._paused = False
        self._start_time = datetime.utcnow()
        self._total_trades = 0
        self._winning_trades = 0

        logger.info("✅ جميع المكونات جاهزة")

    async def run(self) -> bool:
        """تشغيل دورة واحدة وإرجاع False عند فشل يمنع التداول."""
        logger.info("🤖 APEX TRADER - بدء دورة التداول")

        self._running = True

        try:
            await self._load_state()

            if not await self._health_check():
                logger.error("❌ فحص النظام فشل - إيقاف")
                return False

            balance = await self.exchange.get_balance()
            if balance <= 0:
                logger.error(f"❌ رصيد غير صالح: ${balance}")
                return False

            await self._review_open_positions(balance)

            risk_status = self.risk_manager.get_status(balance)
            logger.info(
                f"🛡️ المخاطر: {risk_status['status']} | "
                f"خسارة اليوم: {risk_status['daily_loss_pct']:.1f}%"
            )

            if risk_status["daily_loss_pct"] >= config.risk.max_daily_loss_pct:
                logger.warning("🚨 حد الخسارة اليومية - إيقاف التداول")
                await self.notifier.send_daily_limit_reached(
                    risk_status["daily_loss_pct"]
                )
                await self._save_state()
                return True

            if not self._paused:
                await self._scan_for_opportunities(balance)

            await self._save_state()
            logger.info("✅ اكتملت دورة التداول بنجاح")
            return True

        except Exception as error:
            logger.exception(f"❌ خطأ في الدورة الرئيسية: {error}")
            await self.notifier.send_error(str(error))
            return False

        finally:
            self._running = False
            try:
                await self.exchange.close()
            except Exception:
                pass
            try:
                await self.market_data.close()
            except Exception:
                pass

    async def _health_check(self) -> bool:
        try:
            connected = await self.exchange.check_connection()
            if not connected:
                await self.notifier.send_connection_error()
                return False

            latency = await self.exchange.get_latency()
            if latency > 500:
                logger.warning(f"⚠️ زمن استجابة مرتفع: {latency}ms")

            return True
        except Exception as error:
            logger.error(f"❌ خطأ في فحص الصحة: {error}")
            return False

    async def _review_open_positions(self, balance: float) -> None:
        positions = self.position_manager.get_all_positions()

        if not positions:
            logger.info("📊 لا توجد صفقات مفتوحة")
            return

        logger.info(f"📊 مراجعة {len(positions)} صفقة مفتوحة")

        for position in positions:
            try:
                ticker = await self.exchange.get_ticker(position.symbol)
                current_price = ticker.get("last", 0)

                if not current_price:
                    continue

                df = await self.market_data.get_ohlcv(
                    position.symbol, config.trading.timeframe, limit=50
                )
                atr = 0.0
                if df is not None and len(df) > 14:
                    indicators = self.signal_engine.indicators.calculate_all(df)
                    if indicators:
                        atr = indicators.atr

                action = self.position_manager.update_price(
                    position.id, current_price, atr
                )

                if action and action.get("action") == "close":
                    await self._close_position(
                        position, action["price"], action["reason"], balance
                    )
                elif action and action.get("action") == "partial_close":
                    await self._partial_close_position(
                        position,
                        action["price"],
                        action["percentage"],
                        balance,
                    )

            except Exception as error:
                logger.error(f"❌ خطأ في مراجعة {position.symbol}: {error}")

    async def _scan_for_opportunities(self, balance: float) -> None:
        logger.info(f"🔍 مسح {len(config.trading.symbols)} عملة...")

        opportunities: List[TradeSignal] = []

        for symbol in config.trading.symbols:
            try:
                df = await self.market_data.get_ohlcv(
                    symbol,
                    config.trading.timeframe,
                    limit=100,
                )

                if df is None or len(df) < 60:
                    logger.debug(f"⏭️ {symbol}: بيانات غير كافية")
                    continue

                ticker = await self.exchange.get_ticker(symbol)
                current_price = ticker.get("last", 0)

                if not current_price:
                    continue

                orderbook = await self.exchange.get_orderbook(symbol)

                signal = self.signal_engine.analyze(
                    symbol, df, current_price, orderbook
                )

                if signal.is_valid:
                    opportunities.append(signal)
                    logger.info(
                        f"💡 فرصة: {symbol} {signal.direction.value} "
                        f"| ثقة: {signal.confidence:.1%}"
                    )

            except Exception as error:
                logger.error(f"❌ خطأ في مسح {symbol}: {error}")

        opportunities.sort(key=lambda x: x.confidence, reverse=True)

        for signal in opportunities[:3]:
            await self._execute_signal(signal, balance)
            await asyncio.sleep(1)

    async def _execute_signal(self, signal: TradeSignal, balance: float) -> None:
        risk_check = self.risk_manager.check_signal(signal, balance)

        if not risk_check.approved:
            logger.info(
                f"🚫 رُفضت الصفقة: {signal.symbol} | {risk_check.reason}"
            )
            return

        for warning in risk_check.warnings:
            logger.warning(warning)

        position_value = risk_check.adjusted_size * risk_check.adjusted_leverage
        targets = self.fee_calculator.adjust_targets(
            entry_price=signal.entry_price,
            direction=signal.direction.value.lower(),
            sl_pct=config.risk.default_sl_pct,
            tp1_pct=config.risk.tp1_pct,
            tp2_pct=config.risk.tp2_pct,
            position_size=position_value,
        )

        try:
            order = await self.exchange.place_order(
                symbol=signal.symbol,
                direction=signal.direction.value.lower(),
                size_usd=risk_check.adjusted_size,
                leverage=risk_check.adjusted_leverage,
                stop_loss=targets["stop_loss"],
                take_profit=targets["tp1"],
            )

            if not order:
                logger.error(f"❌ فشل تنفيذ أمر {signal.symbol}")
                return

            position = Position(
                id=str(uuid.uuid4())[:8],
                symbol=signal.symbol,
                direction=signal.direction,
                exchange=self.exchange.active_exchange,
                entry_price=signal.entry_price,
                current_price=signal.entry_price,
                stop_loss=targets["stop_loss"],
                take_profit_1=targets["tp1"],
                take_profit_2=targets["tp2"],
                size_usd=risk_check.adjusted_size,
                leverage=risk_check.adjusted_leverage,
                entry_fee=targets["fees"].entry_fee,
                exit_fee=targets["fees"].exit_fee,
            )

            self.position_manager.add_position(position)
            self.risk_manager.position_opened()
            self._total_trades += 1

            await self.state_manager.save_trade(position, signal)
            await self.notifier.send_trade_opened(position, signal)

        except Exception as error:
            logger.exception(f"❌ خطأ في تنفيذ الصفقة {signal.symbol}: {error}")

    async def _close_position(
        self,
        position: Position,
        close_price: float,
        reason: str,
        balance: float,
    ) -> None:
        try:
            await self.exchange.close_position(
                position.symbol,
                position.direction.value.lower(),
            )

            closed = self.position_manager.close_position(
                position.id, close_price, reason
            )

            if not closed:
                return

            self.risk_manager.position_closed(closed.pnl)

            if closed.pnl > 0:
                self._winning_trades += 1

            await self.state_manager.update_trade_closed(closed)
            await self._apply_compounding(closed.pnl, balance)
            await self.notifier.send_trade_closed(closed, reason)

        except Exception as error:
            logger.exception(f"❌ خطأ في إغلاق {position.symbol}: {error}")

    async def _partial_close_position(
        self,
        position: Position,
        close_price: float,
        percentage: int,
        balance: float,
    ) -> None:
        try:
            logger.info(
                f"🎯 TP1: إغلاق {percentage}% من {position.symbol} @ {close_price}"
            )

            await self.exchange.partial_close(
                position.symbol,
                position.direction.value.lower(),
                percentage,
            )

            partial_pnl = position.unrealized_pnl * (percentage / 100)
            await self.notifier.send_partial_close(
                position, close_price, percentage, partial_pnl
            )

        except Exception as error:
            logger.exception(f"❌ خطأ في الإغلاق الجزئي {position.symbol}: {error}")

    async def _apply_compounding(self, pnl: float, balance: float) -> None:
        if pnl <= 0:
            return

        compound_amount = pnl * config.risk.compounding_rate
        reserved_amount = pnl - compound_amount

        logger.info(
            f"💰 Compounding: إعادة استثمار ${compound_amount:.2f} | "
            f"محجوز: ${reserved_amount:.2f}"
        )

        await self.state_manager.record_compounding(
            compound_amount,
            reserved_amount,
        )

    async def _load_state(self) -> None:
        try:
            state = await self.state_manager.load_state()
            if state:
                if "daily_loss" in state:
                    self.risk_manager._daily_loss = state["daily_loss"]
                if "total_trades" in state:
                    self._total_trades = state["total_trades"]
                logger.info("✅ تم تحميل الحالة السابقة")
            else:
                logger.info("📝 بدء جديد - لا توجد حالة سابقة")

        except Exception as error:
            logger.warning(f"⚠️ لم يتم تحميل الحالة: {error}")

        # --- استرجاع الصفقات المفتوحة الحقيقية ---
        # ضروري لأن GitHub Actions يبدأ container فارغ كل تشغيلة،
        # فالذاكرة (position_manager._positions) تكون فارغة دائماً
        # من غير هذه الخطوة، ولن تعمل إدارة Trailing/Breakeven/TP أبداً.
        try:
            open_positions = await self.state_manager.get_open_positions_from_db()

            for position in open_positions:
                self.position_manager.add_position(position)

            if open_positions:
                self.risk_manager._open_positions = len(open_positions)
                logger.info(
                    f"🔄 تمت استعادة {len(open_positions)} صفقة مفتوحة "
                    f"إلى الذاكرة قبل بدء الدورة"
                )

        except Exception as error:
            logger.warning(f"⚠️ لم يتم استرجاع الصفقات المفتوحة: {error}")

    async def _save_state(self) -> None:
        try:
            state = {
                "daily_loss": self.risk_manager.daily_loss,
                "total_trades": self._total_trades,
                "winning_trades": self._winning_trades,
                "open_positions": self.position_manager.count,
                "timestamp": datetime.utcnow().isoformat(),
            }

            await self.state_manager.save_state(state)
            logger.debug("💾 تم حفظ الحالة")

        except Exception as error:
            logger.warning(f"⚠️ لم يتم حفظ الحالة: {error}")

    def get_stats(self) -> dict:
        win_rate = (
            self._winning_trades / self._total_trades * 100
            if self._total_trades > 0
            else 0
        )

        return {
            "version": self.VERSION,
            "uptime": str(datetime.utcnow() - self._start_time),
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(win_rate, 1),
            "open_positions": self.position_manager.count,
            "unrealized_pnl": round(self.position_manager.total_unrealized_pnl, 4),
        }


async def main():
    """نقطة الدخول - تُستدعى من GitHub Actions"""
    try:
        bot = ApexTrader()
        success = await bot.run()

        if not success:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("⏹️ تم إيقاف البوت يدوياً")

    except Exception as error:
        logger.exception(f"💥 خطأ فادح: {error}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
