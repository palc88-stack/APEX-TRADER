# ======================================
# APEX TRADER - Main Bot Engine
# ======================================
# المحرك الرئيسي للبوت
# يجمع كل المكونات ويشغّلها

import asyncio
import uuid
import time
from datetime import datetime
from typing import Optional, List
from loguru import logger
import sys

from bot.config import config
from bot.core.exchange import ExchangeManager
from bot.core.risk_manager import RiskManager
from bot.core.position_manager import PositionManager, Position
from bot.core.fee_calculator import FeeCalculator
from bot.signals.signal_engine import (
    SignalEngine, TradeSignal, TradeDirection, TradingMode
)
from bot.data.state_manager import StateManager
from bot.data.market_data import MarketDataManager
from bot.notifications.telegram_notifier import TelegramNotifier


# إعداد نظام السجلات
logger.remove()
logger.add(
    sys.stdout,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO"
)
logger.add(
    "logs/apex_trader_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)


class ApexTrader:
    """
    APEX TRADER - المحرك الرئيسي
    
    يدير دورة حياة البوت الكاملة:
    1. جمع البيانات
    2. تحليل الفرص
    3. إدارة المخاطر
    4. تنفيذ الصفقات
    5. مراقبة المراكز
    6. الإشعارات
    """
    
    VERSION = "1.0.0"
    
    def __init__(self):
        logger.info(f"🚀 تشغيل APEX TRADER v{self.VERSION}")
        
        # التحقق من الإعدادات
        if not config.validate_all():
            raise RuntimeError("❌ فشل تحميل الإعدادات!")
        
        # تهيئة المكونات
        self.exchange = ExchangeManager()
        self.risk_manager = RiskManager()
        self.position_manager = PositionManager()
        self.signal_engine = SignalEngine()
        self.fee_calculator = FeeCalculator()
        self.state_manager = StateManager()
        self.market_data = MarketDataManager()
        self.notifier = TelegramNotifier()
        
        # حالة البوت
        self._running = False
        self._paused = False
        self._start_time = datetime.utcnow()
        self._total_trades = 0
        self._winning_trades = 0
        
        logger.info("✅ جميع المكونات جاهزة")
    
    async def run(self) -> None:
        """
        تشغيل البوت - الدورة الرئيسية
        تُنفَّذ كل 5 دقائق عبر GitHub Actions
        """
        logger.info("=" * 60)
        logger.info("🤖 APEX TRADER - بدء دورة التداول")
        logger.info(
            f"🌍 البيئة: {config.environment.upper()}"
        )
        logger.info("=" * 60)
        
        self._running = True
        
        try:
            # تحميل الحالة السابقة
            await self._load_state()
            
            # الفحص الأولي للنظام
            if not await self._health_check():
                logger.error("❌ فحص النظام فشل - إيقاف")
                return
            
            # جلب الرصيد
            balance = await self.exchange.get_balance()
            if balance <= 0:
                logger.error(f"❌ رصيد غير صالح: ${balance}")
                return
            
            logger.info(f"💰 الرصيد: ${balance:.2f}")
            
            # مراجعة الصفقات المفتوحة
            await self._review_open_positions(balance)
            
            # فحص حالة المخاطر
            risk_status = self.risk_manager.get_status(balance)
            logger.info(
                f"🛡️ المخاطر: {risk_status['status']} | "
                f"خسارة اليوم: {risk_status['daily_loss_pct']:.1f}%"
            )
            
            # إذا وصلنا للحد اليومي = توقف
            if risk_status['daily_loss_pct'] >= config.risk.max_daily_loss_pct:
                logger.warning("🚨 حد الخسارة اليومية - إيقاف التداول")
                await self.notifier.send_daily_limit_reached(
                    risk_status['daily_loss_pct']
                )
                await self._save_state()
                return
            
            # البحث عن فرص التداول
            if not self._paused:
                await self._scan_for_opportunities(balance)
            
            # حفظ الحالة
            await self._save_state()
            
            logger.info("✅ اكتملت دورة التداول بنجاح")
            
        except Exception as e:
            logger.exception(f"❌ خطأ في الدورة الرئيسية: {e}")
            await self.notifier.send_error(str(e))
        finally:
            self._running = False
    
    async def _health_check(self) -> bool:
        """فحص صحة النظام قبل التداول"""
        try:
            # فحص الاتصال بالمنصة
            connected = await self.exchange.check_connection()
            if not connected:
                logger.error("❌ لا يوجد اتصال بالمنصة!")
                await self.notifier.send_connection_error()
                return False
            
            # فحص زمن الاستجابة
            latency = await self.exchange.get_latency()
            if latency > 500:  # 500ms حد أقصى
                logger.warning(f"⚠️ زمن استجابة مرتفع: {latency}ms")
            
            logger.info(f"✅ صحة النظام: جيدة | زمن: {latency}ms")
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في فحص الصحة: {e}")
            return False
    
    async def _review_open_positions(self, balance: float) -> None:
        """مراجعة الصفقات المفتوحة وتحديثها"""
        positions = self.position_manager.get_all_positions()
        
        if not positions:
            logger.info("📊 لا توجد صفقات مفتوحة")
            return
        
        logger.info(f"📊 مراجعة {len(positions)} صفقة مفتوحة")
        
        for position in positions:
            try:
                # جلب السعر الحالي
                ticker = await self.exchange.get_ticker(position.symbol)
                current_price = ticker.get('last', 0)
                
                if not current_price:
                    continue
                
                # جلب ATR لـ Trailing ديناميكي
                df = await self.market_data.get_ohlcv(
                    position.symbol, 
                    config.trading.timeframe,
                    limit=50
                )
                atr = 0.0
                if df is not None and len(df) > 14:
                    indicators = self.signal_engine.indicators.calculate_all(df)
                    if indicators:
                        atr = indicators.atr
                
                # تحديث الصفقة
                action = self.position_manager.update_price(
                    position.id, current_price, atr
                )
                
                if not action:
                    continue
                
                # تنفيذ الإجراء المطلوب
                if action['action'] == 'close':
                    await self._close_position(
                        position, 
                        action['price'],
                        action['reason'],
                        balance
                    )
                
                elif action['action'] == 'partial_close':
                    await self._partial_close_position(
                        position,
                        action['price'],
                        action['percentage'],
                        balance
                    )
                    
            except Exception as e:
                logger.error(
                    f"❌ خطأ في مراجعة {position.symbol}: {e}"
                )
    
    async def _scan_for_opportunities(self, balance: float) -> None:
        """
        مسح العملات بحثاً عن فرص التداول
        """
        logger.info(
            f"🔍 مسح {len(config.trading.symbols)} عملة..."
        )
        
        opportunities: List[TradeSignal] = []
        
        for symbol in config.trading.symbols:
            try:
                # جلب البيانات
                df = await self.market_data.get_ohlcv(
                    symbol,
                    config.trading.timeframe,
                    limit=100
                )
                
                if df is None or len(df) < 60:
                    logger.debug(f"⏭️ {symbol}: بيانات غير كافية")
                    continue
                
                # السعر الحالي
                ticker = await self.exchange.get_ticker(symbol)
                current_price = ticker.get('last', 0)
                
                if not current_price:
                    continue
                
                # Order Book
                orderbook = await self.exchange.get_orderbook(symbol)
                
                # تحليل الفرصة
                signal = self.signal_engine.analyze(
                    symbol, df, current_price, orderbook
                )
                
                if signal.is_valid:
                    opportunities.append(signal)
                    logger.info(
                        f"💡 فرصة: {symbol} {signal.direction.value} "
                        f"| ثقة: {signal.confidence:.1%}"
                    )
                    
            except Exception as e:
                logger.error(f"❌ خطأ في مسح {symbol}: {e}")
        
        # ترتيب الفرص حسب الثقة
        opportunities.sort(key=lambda x: x.confidence, reverse=True)
        
        # تنفيذ أفضل الفرص
        for signal in opportunities[:3]:  # أفضل 3 فرص
            await self._execute_signal(signal, balance)
            
            # تأخير بين الصفقات
            await asyncio.sleep(1)
    
    async def _execute_signal(
        self, 
        signal: TradeSignal,
        balance: float
    ) -> None:
        """
        تنفيذ إشارة التداول
        
        Args:
            signal: الإشارة المراد تنفيذها
            balance: الرصيد المتاح
        """
        # فحص المخاطر
        risk_check = self.risk_manager.check_signal(signal, balance)
        
        if not risk_check.approved:
            logger.info(
                f"🚫 رُفضت الصفقة: {signal.symbol} | "
                f"{risk_check.reason}"
            )
            return
        
        # إرسال تحذيرات
        for warning in risk_check.warnings:
            logger.warning(warning)
        
        # حساب الأهداف بعد العمولات
        position_value = (
            risk_check.adjusted_size * risk_check.adjusted_leverage
        )
        targets = self.fee_calculator.adjust_targets(
            entry_price=signal.entry_price,
            direction=signal.direction.value.lower(),
            sl_pct=config.risk.default_sl_pct,
            tp1_pct=config.risk.tp1_pct,
            tp2_pct=config.risk.tp2_pct,
            position_size=position_value
        )
        
        try:
            # تنفيذ الأمر على المنصة
            order = await self.exchange.place_order(
                symbol=signal.symbol,
                direction=signal.direction.value.lower(),
                size_usd=risk_check.adjusted_size,
                leverage=risk_check.adjusted_leverage,
                stop_loss=targets['stop_loss'],
                take_profit=targets['tp1']
            )
            
            if not order:
                logger.error(f"❌ فشل تنفيذ أمر {signal.symbol}")
                return
            
            # إنشاء سجل الصفقة
            position = Position(
                id=str(uuid.uuid4())[:8],
                symbol=signal.symbol,
                direction=signal.direction,
                exchange=self.exchange.active_exchange,
                entry_price=signal.entry_price,
                current_price=signal.entry_price,
                stop_loss=targets['stop_loss'],
                take_profit_1=targets['tp1'],
                take_profit_2=targets['tp2'],
                size_usd=risk_check.adjusted_size,
                leverage=risk_check.adjusted_leverage,
                entry_fee=targets['fees'].entry_fee,
                exit_fee=targets['fees'].exit_fee
            )
            
            # تسجيل الصفقة
            self.position_manager.add_position(position)
            self.risk_manager.position_opened()
            self._total_trades += 1
            
            # حفظ في قاعدة البيانات
            await self.state_manager.save_trade(position, signal)
            
            # إشعار Telegram
            await self.notifier.send_trade_opened(position, signal)
            
            logger.info(
                f"✅ صفقة مفتوحة: {position.symbol} "
                f"{position.direction.value} @ "
                f"{position.entry_price} | "
                f"حجم: ${position.size_usd:.2f} | "
                f"رافعة: {position.leverage}x"
            )
            
        except Exception as e:
            logger.exception(
                f"❌ خطأ في تنفيذ الصفقة {signal.symbol}: {e}"
            )
    
    async def _close_position(
        self,
        position: Position,
        close_price: float,
        reason: str,
        balance: float
    ) -> None:
        """إغلاق صفقة كاملة"""
        try:
            # إغلاق على المنصة
            await self.exchange.close_position(
                position.symbol,
                position.direction.value.lower()
            )
            
            # تسجيل الإغلاق
            closed = self.position_manager.close_position(
                position.id, close_price, reason
            )
            
            if not closed:
                return
            
            # تحديث إدارة المخاطر
            self.risk_manager.position_closed(closed.pnl)
            
            # تحديث إحصاءات
            if closed.pnl > 0:
                self._winning_trades += 1
            
            # حفظ في قاعدة البيانات
            await self.state_manager.update_trade_closed(closed)
            
            # تحديث Compounding
            await self._apply_compounding(closed.pnl, balance)
            
            # إشعار Telegram
            await self.notifier.send_trade_closed(closed, reason)
            
        except Exception as e:
            logger.exception(
                f"❌ خطأ في إغلاق {position.symbol}: {e}"
            )
    
    async def _partial_close_position(
        self,
        position: Position,
        close_price: float,
        percentage: int,
        balance: float
    ) -> None:
        """إغلاق جزئي عند TP1"""
        try:
            logger.info(
                f"🎯 TP1: إغلاق {percentage}% من "
                f"{position.symbol} @ {close_price}"
            )
            
            # إغلاق جزئي على المنصة
            await self.exchange.partial_close(
                position.symbol,
                position.direction.value.lower(),
                percentage
            )
            
            # حساب الربح الجزئي
            partial_pnl = position.unrealized_pnl * (percentage / 100)
            
            # إشعار
            await self.notifier.send_partial_close(
                position, close_price, percentage, partial_pnl
            )
            
        except Exception as e:
            logger.exception(
                f"❌ خطأ في الإغلاق الجزئي {position.symbol}: {e}"
            )
    
    async def _apply_compounding(
        self, 
        pnl: float,
        balance: float
    ) -> None:
        """
        تطبيق نظام Compounding على الأرباح
        70% يعود للتداول، 30% محجوز
        """
        if pnl <= 0:
            return
        
        compound_amount = pnl * config.risk.compounding_rate
        reserved_amount = pnl - compound_amount
        
        logger.info(
            f"💰 Compounding: إعادة استثمار "
            f"${compound_amount:.2f} | "
            f"محجوز: ${reserved_amount:.2f}"
        )
        
        # حفظ في قاعدة البيانات
        await self.state_manager.record_compounding(
            compound_amount, reserved_amount
        )
    
    async def _load_state(self) -> None:
        """تحميل الحالة السابقة عند الإقلاع"""
        try:
            state = await self.state_manager.load_state()
            
            if state:
                # استعادة الخسارة اليومية
                if 'daily_loss' in state:
                    self.risk_manager._daily_loss = state['daily_loss']
                
                if 'total_trades' in state:
                    self._total_trades = state['total_trades']
                
                logger.info("✅ تم تحميل الحالة السابقة")
            else:
                logger.info("📝 بدء جديد - لا توجد حالة سابقة")
                
        except Exception as e:
            logger.warning(f"⚠️ لم يتم تحميل الحالة: {e}")
    
    async def _save_state(self) -> None:
        """حفظ الحالة الحالية"""
        try:
            state = {
                "daily_loss": self.risk_manager.daily_loss,
                "total_trades": self._total_trades,
                "winning_trades": self._winning_trades,
                "open_positions": self.position_manager.count,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await self.state_manager.save_state(state)
            logger.debug("💾 تم حفظ الحالة")
            
        except Exception as e:
            logger.warning(f"⚠️ لم يتم حفظ الحالة: {e}")
    
    def get_stats(self) -> dict:
        """إحصاءات البوت الكاملة"""
        win_rate = (
            self._winning_trades / self._total_trades * 100
            if self._total_trades > 0 else 0
        )
        
        return {
            "version": self.VERSION,
            "uptime": str(datetime.utcnow() - self._start_time),
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(win_rate, 1),
            "open_positions": self.position_manager.count,
            "unrealized_pnl": round(
                self.position_manager.total_unrealized_pnl, 4
            )
        }


# ======================================
# نقطة الدخول الرئيسية
# ======================================

async def main():
    """نقطة الدخول - تُستدعى من GitHub Actions"""
    try:
        bot = ApexTrader()
        await bot.run()
    except KeyboardInterrupt:
        logger.info("⏹️ تم إيقاف البوت يدوياً")
    except Exception as e:
        logger.exception(f"💥 خطأ فادح: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
