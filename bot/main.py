import asyncio
import os
import sys
import uuid
from datetime import date, datetime
from typing import List

from loguru import logger

from bot.config import config
from bot.core.exchange import ExchangeManager
from bot.core.risk_manager import RiskManager
from bot.core.position_manager import (
    Position,
    PositionManager,
)
from bot.core.fee_calculator import FeeCalculator
from bot.signals.signal_engine import (
    SignalEngine,
    TradeSignal,
)
from bot.data.state_manager import StateManager
from bot.data.market_data import MarketDataManager
from bot.notifications.telegram_notifier import (
    TelegramNotifier,
)


os.makedirs("logs", exist_ok=True)

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
    VERSION = "1.1.0"

    def __init__(self):
        logger.info(
            "🚀 تشغيل APEX TRADER v{}",
            self.VERSION,
        )

        if not config.validate_all():
            raise RuntimeError(
                "❌ فشل تحميل الإعدادات"
            )

        self.exchange = ExchangeManager()
        self.risk_manager = RiskManager()
        self.position_manager = PositionManager()
        self.signal_engine = SignalEngine()
        self.fee_calculator = FeeCalculator(
            exchange=config.exchange.primary_exchange()
        )
        self.state_manager = StateManager()
        self.market_data = MarketDataManager()
        self.notifier = TelegramNotifier()

        self._running = False
        self._paused = False
        self._start_time = datetime.utcnow()
        self._total_trades = 0
        self._winning_trades = 0

        logger.info(
            "✅ جميع المكونات جاهزة | exchanges={}",
            ", ".join(
                self.exchange.available_exchanges()
            ),
        )

    async def run(self) -> bool:
        logger.info(
            "🤖 APEX TRADER - بدء دورة التداول"
        )

        self._running = True

        try:
            await self._load_state()

            if not await self._health_check():
                logger.error(
                    "❌ فحص النظام فشل - إيقاف"
                )
                return False

            balance = await self.exchange.get_balance()

            if balance <= 0:
                logger.error(
                    "❌ رصيد غير صالح: ${}",
                    balance,
                )
                return False

            self.risk_manager.set_day_start_balance(
                balance
            )

            await self._review_open_positions(
                balance
            )

            risk_status = (
                self.risk_manager.get_status(balance)
            )

            daily_loss_pct = (
                risk_status.get(
                    "daily_loss_pct"
                )
            )

            if daily_loss_pct is None:
                logger.error(
                    "❌ تعذر حساب الخسارة اليومية"
                )
                return False

            logger.info(
                "🛡️ المخاطر: {} | خسارة اليوم: {:.2f}%",
                risk_status["status"],
                daily_loss_pct,
            )

            if (
                daily_loss_pct
                >= config.risk.max_daily_loss_pct
            ):
                logger.warning(
                    "🚨 تم الوصول إلى حد الخسارة اليومية"
                )

                await self.notifier.send_daily_limit_reached(
                    daily_loss_pct
                )

                await self._save_state(balance)
                return True

            if not self._paused:
                await self._scan_for_opportunities(
                    balance
                )

            await self._save_state(balance)

            logger.info(
                "✅ اكتملت دورة التداول بنجاح"
            )
            return True

        except Exception as error:
            logger.exception(
                "❌ خطأ في الدورة الرئيسية: {}",
                error,
            )

            try:
                await self.notifier.send_error(
                    str(error)
                )
            except Exception:
                pass

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
        statuses = (
            await self.exchange.check_all_connections()
        )

        if not statuses:
            await self.notifier.send_connection_error()
            return False

        failed = [
            name
            for name, connected in statuses.items()
            if not connected
        ]

        if failed:
            logger.error(
                "❌ منصات غير متاحة: {}",
                ", ".join(failed),
            )
            await self.notifier.send_connection_error()
            return False

        logger.info(
            "✅ جميع المنصات تعمل: {}",
            ", ".join(statuses.keys()),
        )

        return True

    async def _review_open_positions(
        self,
        balance: float,
    ) -> None:
        positions = (
            self.position_manager.get_all_positions()
        )

        if not positions:
            logger.info(
                "📊 لا توجد صفقات مفتوحة"
            )
            return

        logger.info(
            "📊 مراجعة {} صفقة مفتوحة",
            len(positions),
        )

        for position in positions:
            try:
                ticker = await self.exchange.get_ticker(
                    position.symbol,
                    position.exchange,
                )

                current_price = ticker.get(
                    "last",
                    0,
                )

                if not current_price:
                    continue

                dataframe = (
                    await self.market_data.get_ohlcv(
                        position.symbol,
                        config.trading.timeframe,
                        limit=50,
                    )
                )

                atr = 0.0

                if (
                    dataframe is not None
                    and len(dataframe) > 14
                ):
                    indicators = (
                        self.signal_engine
                        .indicators
                        .calculate_all(dataframe)
                    )

                    if indicators:
                        atr = indicators.atr

                action = (
                    self.position_manager.update_price(
                        position.id,
                        current_price,
                        atr,
                    )
                )

                if not action:
                    continue

                if action.get("action") == "close":
                    await self._close_position(
                        position,
                        action["price"],
                        action["reason"],
                        balance,
                    )

                elif (
                    action.get("action")
                    == "partial_close"
                ):
                    await self._partial_close_position(
                        position,
                        action["price"],
                        action["percentage"],
                        balance,
                    )

            except Exception as error:
                logger.exception(
                    "❌ خطأ في مراجعة {}: {}",
                    position.symbol,
                    error,
                )

    async def _scan_for_opportunities(
        self,
        balance: float,
    ) -> None:
        logger.info(
            "🔍 مسح {} عملة",
            len(config.trading.symbols),
        )

        opportunities: List[TradeSignal] = []

        for symbol in config.trading.symbols:
            try:
                dataframe = (
                    await self.market_data.get_ohlcv(
                        symbol,
                        config.trading.timeframe,
                        limit=100,
                    )
                )

                if (
                    dataframe is None
                    or len(dataframe) < 60
                ):
                    logger.debug(
                        "⏭️ {}: بيانات غير كافية",
                        symbol,
                    )
                    continue

                ticker = await self.exchange.get_ticker(
                    symbol
                )

                current_price = ticker.get(
                    "last",
                    0,
                )

                if not current_price:
                    continue

                orderbook = (
                    await self.exchange.get_orderbook(
                        symbol
                    )
                )

                signal = self.signal_engine.analyze(
                    symbol,
                    dataframe,
                    current_price,
                    orderbook,
                )

                if signal.is_valid:
                    opportunities.append(signal)

                    logger.info(
                        "💡 فرصة: {} {} | ثقة: {:.1%}",
                        symbol,
                        signal.direction.value,
                        signal.confidence,
                    )

            except Exception as error:
                logger.exception(
                    "❌ خطأ في مسح {}: {}",
                    symbol,
                    error,
                )

        opportunities.sort(
            key=lambda item: item.confidence,
            reverse=True,
        )

        available_slots = max(
            0,
            5 - self.position_manager.count,
        )

        for signal in opportunities[:available_slots]:
            await self._execute_signal(
                signal,
                balance,
            )
            await asyncio.sleep(1)

    async def _execute_signal(
        self,
        signal: TradeSignal,
        balance: float,
    ) -> None:
        risk_check = (
            self.risk_manager
            .approve_and_reserve_position(
                signal,
                balance,
            )
        )

        if not risk_check.approved:
            logger.info(
                "🚫 رُفضت الصفقة {}: {}",
                signal.symbol,
                risk_check.reason,
            )
            return

        for warning in risk_check.warnings:
            logger.warning(warning)

        position_value = (
            risk_check.adjusted_size
            * risk_check.adjusted_leverage
        )

        targets = self.fee_calculator.adjust_targets(
            entry_price=signal.entry_price,
            direction=signal.direction.value.lower(),
            sl_pct=config.risk.default_sl_pct,
            tp1_pct=config.risk.tp1_pct,
            tp2_pct=config.risk.tp2_pct,
            position_size=position_value,
        )

        reservation_id = (
            risk_check.reservation_id
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
                if reservation_id:
                    self.risk_manager.release_reserved_position(
                        reservation_id
                    )
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

            self.position_manager.add_position(
                position
            )

            self._total_trades += 1

            await self.state_manager.save_trade(
                position,
                signal,
            )

            await self.notifier.send_trade_opened(
                position,
                signal,
            )

            logger.info(
                "✅ تم تسجيل الصفقة {}",
                signal.symbol,
            )

        except Exception as error:
            if reservation_id:
                self.risk_manager.release_reserved_position(
                    reservation_id
                )

            logger.exception(
                "❌ خطأ تنفيذ {}: {}",
                signal.symbol,
                error,
            )

    async def _close_position(
        self,
        position: Position,
        close_price: float,
        reason: str,
        balance: float,
    ) -> None:
        try:
            closed_on_exchange = (
                await self.exchange.close_position(
                    position.symbol,
                    position.direction.value.lower(),
                    position.exchange,
                )
            )

            if not closed_on_exchange:
                logger.error(
                    "❌ فشل إغلاق المنصة {}",
                    position.symbol,
                )
                return

            closed = (
                self.position_manager.close_position(
                    position.id,
                    close_price,
                    reason,
                )
            )

            if not closed:
                return

            self.risk_manager.position_closed(
                closed.pnl
            )

            if closed.pnl > 0:
                self._winning_trades += 1

            await self.state_manager.update_trade_closed(
                closed
            )

            await self._apply_compounding(
                closed.pnl,
                balance,
            )

            await self.notifier.send_trade_closed(
                closed,
                reason,
            )

        except Exception as error:
            logger.exception(
                "❌ خطأ إغلاق {}: {}",
                position.symbol,
                error,
            )

    async def _partial_close_position(
        self,
        position: Position,
        close_price: float,
        percentage: int,
        balance: float,
    ) -> None:
        try:
            success = (
                await self.exchange.partial_close(
                    position.symbol,
                    position.direction.value.lower(),
                    percentage,
                    position.exchange,
                )
            )

            if not success:
                logger.error(
                    "❌ فشل الإغلاق الجزئي {}",
                    position.symbol,
                )
                return

            partial_pnl = (
                position.unrealized_pnl
                * percentage
                / 100
            )

            position.size_usd *= (
                1 - percentage / 100
            )

            await self.notifier.send_partial_close(
                position,
                close_price,
                percentage,
                partial_pnl,
            )

        except Exception as error:
            logger.exception(
                "❌ خطأ الإغلاق الجزئي {}: {}",
                position.symbol,
                error,
            )

    async def _apply_compounding(
        self,
        pnl: float,
        balance: float,
    ) -> None:
        if pnl <= 0:
            return

        compound_amount = (
            pnl * config.risk.compounding_rate
        )
        reserved_amount = pnl - compound_amount

        await self.state_manager.record_compounding(
            compound_amount,
            reserved_amount,
        )

    async def _load_state(self) -> None:
        try:
            state = (
                await self.state_manager.load_state()
            )

            if state:
                saved_date = state.get("date")
                state_date = None

                if saved_date:
                    try:
                        state_date = date.fromisoformat(
                            saved_date
                        )
                    except ValueError:
                        logger.warning(
                            "⚠️ تاريخ الحالة غير صالح: {}",
                            saved_date,
                        )

                self.risk_manager.restore_daily_state(
                    daily_loss=state.get(
                        "daily_loss",
                        0.0,
                    ),
                    daily_trades=state.get(
                        "daily_trades",
                        state.get(
                            "total_trades",
                            0,
                        ),
                    ),
                    state_date=state_date,
                    day_start_balance=state.get(
                        "day_start_balance"
                    ),
                )

                self._total_trades = int(
                    state.get(
                        "total_trades",
                        0,
                    )
                )

                self._winning_trades = int(
                    state.get(
                        "winning_trades",
                        0,
                    )
                )

                logger.info(
                    "✅ تم تحميل الحالة السابقة"
                )
            else:
                logger.info(
                    "📝 بدء جديد - لا توجد حالة سابقة"
                )

        except Exception as error:
            logger.warning(
                "⚠️ فشل تحميل الحالة: {}",
                error,
            )

        try:
            open_positions = (
                await self.state_manager
                .get_open_positions_from_db()
            )

            for position in open_positions:
                self.position_manager.add_position(
                    position
                )

            self.risk_manager.restore_open_positions_count(
                len(open_positions)
            )

        except Exception as error:
            logger.warning(
                "⚠️ فشل استعادة الصفقات المفتوحة: {}",
                error,
            )

    async def _save_state(
        self,
        balance: float,
    ) -> None:
        try:
            state = {
                "daily_loss": (
                    self.risk_manager.daily_loss
                ),
                "daily_trades": (
                    self.risk_manager.daily_trades
                ),
                "total_trades": self._total_trades,
                "winning_trades": self._winning_trades,
                "open_positions": (
                    self.position_manager.count
                ),
                "date": (
                    datetime.utcnow()
                    .date()
                    .isoformat()
                ),
                "day_start_balance": balance,
                "timestamp": datetime.utcnow().isoformat(),
            }

            await self.state_manager.save_state(
                state
            )

        except Exception as error:
            logger.warning(
                "⚠️ فشل حفظ الحالة: {}",
                error,
            )

    def get_stats(self) -> dict:
        win_rate = (
            self._winning_trades
            / self._total_trades
            * 100
            if self._total_trades > 0
            else 0
        )

        return {
            "version": self.VERSION,
            "uptime": str(
                datetime.utcnow()
                - self._start_time
            ),
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(win_rate, 1),
            "open_positions": (
                self.position_manager.count
            ),
            "unrealized_pnl": round(
                self.position_manager.total_unrealized_pnl,
                4,
            ),
        }


async def main():
    try:
        bot = ApexTrader()
        success = await bot.run()

        if not success:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info(
            "⏹️ تم إيقاف البوت يدوياً"
        )

    except Exception as error:
        logger.exception(
            "💥 خطأ فادح: {}",
            error,
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
