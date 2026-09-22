# ======================================
# APEX TRADER - Telegram Notifier
# ======================================
# إشعارات Telegram الكاملة
# رسائل منسقة وآمنة

import asyncio
from typing import Optional
from datetime import datetime, timezone
from loguru import logger
import aiohttp

from bot.config import config
from bot.core.position_manager import Position


class TelegramNotifier:
    """
    مُرسِل إشعارات Telegram الاحترافي

    جميع الرسائل:
    - منسقة بـ HTML
    - لا تحتوي بيانات حساسة
    - موجزة وواضحة
    """

    API_URL = (
        "https://api.telegram.org/bot{token}/sendMessage"
    )
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # ثانيتان

    def __init__(self):
        self.token = config.telegram.bot_token
        self.chat_id = config.telegram.chat_id
        self._enabled = bool(
            self.token and self.chat_id
        )

        if self._enabled:
            logger.info("✅ Telegram جاهز للإشعارات")
        else:
            logger.warning(
                "⚠️ Telegram غير مضبوط - "
                "الإشعارات معطّلة"
            )

    async def send(
        self,
        message: str,
        parse_mode: str = "HTML"
    ) -> bool:
        """
        إرسال رسالة مع إعادة المحاولة

        Args:
            message: نص الرسالة
            parse_mode: HTML أو Markdown

        Returns:
            bool: نجح الإرسال؟
        """
        if not self._enabled:
            # في وضع التطوير نطبع فقط
            logger.debug(
                f"📤 [Telegram محاكاة]: "
                f"{message[:80]}..."
            )
            return True

        url = self.API_URL.format(token=self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(
                            total=10
                        )
                    ) as response:
                        if response.status == 200:
                            return True

                        # معالجة Rate Limit
                        if response.status == 429:
                            retry_after = int(
                                response.headers.get(
                                    'Retry-After', 5
                                )
                            )
                            logger.warning(
                                f"⏳ Rate limit - "
                                f"انتظار {retry_after}s"
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        error_text = await response.text()
                        logger.error(
                            f"❌ Telegram خطأ "
                            f"{response.status}: "
                            f"{error_text[:100]}"
                        )
                        return False

            except asyncio.TimeoutError:
                logger.warning(
                    f"⚠️ Telegram timeout "
                    f"(محاولة {attempt}/{self.MAX_RETRIES})"
                )
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY)

            except aiohttp.ClientError as e:
                logger.error(f"❌ Telegram network: {e}")
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY)

            except Exception as e:
                logger.error(
                    f"❌ Telegram خطأ غير متوقع: {e}"
                )
                return False

        return False

    async def send_trade_opened(
        self,
        position: Position,
        signal=None
    ) -> None:
        """إشعار فتح صفقة جديدة"""
        direction_icon = (
            "🟢⬆️"
            if position.direction.value == "LONG"
            else "🔴⬇️"
        )

        mode_icons = {
            "SNIPER": "🎯",
            "HUNTER": "🏹",
            "FARMER": "🌾",
            "EXPLOSION": "💥"
        }

        mode = (
            signal.mode.value if signal else "UNKNOWN"
        )
        mode_icon = mode_icons.get(mode, "📊")
        confidence = signal.confidence if signal else 0.0
        is_explosion = (
            signal.is_explosion if signal else False
        )

        explosion_line = (
            "\n💥 <b>انفجار سعري مكتشف!</b>"
            if is_explosion else ""
        )

        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"{mode_icon} <b>{mode} - صفقة جديدة</b>"
            f"{explosion_line}\n\n"
            f"{direction_icon} <b>{position.symbol}</b> "
            f"{position.direction.value}\n\n"
            f"📊 <b>تفاصيل:</b>\n"
            f"├ سعر الدخول: "
            f"<code>${position.entry_price:,.4f}</code>\n"
            f"├ الهامش: "
            f"<code>${position.size_usd:.2f}</code>\n"
            f"├ الرافعة: "
            f"<code>{position.leverage}x</code>\n"
            f"└ القيمة: "
            f"<code>${position.position_value:.2f}</code>\n\n"
            f"🎯 <b>الأهداف:</b>\n"
            f"├ وقف الخسارة: "
            f"<code>${position.stop_loss:,.4f}</code>\n"
            f"├ الهدف 1: "
            f"<code>${position.take_profit_1:,.4f}</code>\n"
            f"└ الهدف 2: "
            f"<code>${position.take_profit_2:,.4f}</code>\n\n"
            f"💸 عمولات: "
            f"<code>${(position.entry_fee + position.exit_fee):.4f}</code>\n"
            f"🎯 الثقة: <code>{confidence:.1%}</code>\n"
            f"🏦 المنصة: <code>{position.exchange.upper()}</code>\n"
            f"🕐 <code>"
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
            f"</code>"
        )

        await self.send(message)

    async def send_trade_closed(
        self,
        position: Position,
        reason: str
    ) -> None:
        """إشعار إغلاق صفقة"""
        is_profit = position.pnl >= 0
        result_icon = "✅" if is_profit else "❌"

        reason_labels = {
            "tp1": "🎯 الهدف الأول",
            "tp2": "🎯🎯 الهدف الثاني",
            "stop_loss": "🛡️ وقف الخسارة",
            "trailing_stop": "🔄 Trailing Stop",
            "manual": "👤 إغلاق يدوي"
        }

        close_reason = reason_labels.get(reason, reason)

        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"{result_icon} <b>صفقة مغلقة</b>\n\n"
            f"📊 <b>{position.symbol}</b> "
            f"{position.direction.value}\n"
            f"└ السبب: {close_reason}\n\n"
            f"💰 <b>النتيجة:</b>\n"
            f"├ P&L: <code>${position.pnl:+.4f}</code>\n"
            f"├ النسبة: <code>{position.pnl_pct:+.2f}%</code>\n"
            f"└ المدة: "
            f"<code>{position.duration_minutes:.1f} دقيقة</code>"
        )

        await self.send(message)

    async def send_partial_close(
        self,
        position: Position,
        price: float,
        percentage: int,
        partial_pnl: float
    ) -> None:
        """إشعار إغلاق جزئي عند TP1"""
        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"🎯 <b>إغلاق جزئي - TP1</b>\n\n"
            f"📊 <b>{position.symbol}</b>\n"
            f"├ السعر: <code>${price:,.4f}</code>\n"
            f"├ المُغلَق: <code>{percentage}%</code>\n"
            f"└ ربح جزئي: <code>${partial_pnl:+.4f}</code>\n\n"
            f"🔄 <i>Trailing يحمي الباقي...</i>"
        )

        await self.send(message)

    async def send_daily_report(
        self,
        stats: dict,
        balance: float
    ) -> None:
        """التقرير اليومي الكامل"""
        win_rate = float(stats.get("win_rate", 0))
        net_pnl = float(stats.get("net_pnl", 0))
        total_trades = int(stats.get("total_trades", 0))
        winning = int(stats.get("winning_trades", 0))
        losing = int(stats.get("losing_trades", 0))
        total_fees = float(stats.get("total_fees", 0))

        # تحديد إيموجي النتيجة
        if win_rate >= 65:
            performance_icon = "🟢 ممتاز"
        elif win_rate >= 55:
            performance_icon = "🟡 جيد"
        else:
            performance_icon = "🔴 يحتاج مراجعة"

        pnl_icon = "📈" if net_pnl >= 0 else "📉"

        message = (
            f"⬡ <b>APEX TRADER - تقرير يومي</b>\n"
            f"📅 {stats.get('date', date.today().isoformat())}\n\n"
            f"💰 <b>المالية:</b>\n"
            f"├ الرصيد: <code>${balance:.2f}</code>\n"
            f"├ {pnl_icon} صافي اليوم: "
            f"<code>${net_pnl:+.4f}</code>\n"
            f"└ الرسوم: <code>${total_fees:.4f}</code>\n\n"
            f"📊 <b>الصفقات:</b>\n"
            f"├ الإجمالي: <code>{total_trades}</code>\n"
            f"├ رابحة ✅: <code>{winning}</code>\n"
            f"├ خاسرة ❌: <code>{losing}</code>\n"
            f"└ Win Rate: <code>{win_rate:.1f}%</code>\n\n"
            f"🏆 الأداء: {performance_icon}"
        )

        await self.send(message)

    async def send_daily_limit_reached(
        self,
        loss_pct: float
    ) -> None:
        """إشعار الوصول لحد الخسارة اليومية"""
        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"🚨 <b>حد الخسارة اليومية!</b>\n\n"
            f"الخسارة: <code>{loss_pct:.1f}%</code>\n\n"
            f"⏸️ البوت متوقف حتى الغد\n"
            f"💤 يعود في 00:00 UTC"
        )

        await self.send(message)

    async def send_error(self, error_msg: str) -> None:
        """إشعار خطأ في النظام"""
        # لا نرسل رسائل خطأ طويلة
        short_error = error_msg[:150].replace(
            '<', '&lt;'
        ).replace('>', '&gt;')

        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"⚠️ <b>تنبيه نظام</b>\n\n"
            f"<code>{short_error}</code>\n\n"
            f"🔄 إعادة المحاولة في الدورة القادمة"
        )

        await self.send(message)

    async def send_connection_error(self) -> None:
        """إشعار انقطاع الاتصال بالمنصة"""
        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"🔴 <b>انقطاع الاتصال!</b>\n\n"
            f"الصفقات محمية بـ SL على المنصة\n"
            f"🔄 إعادة المحاولة تلقائياً..."
        )

        await self.send(message)

    async def send_startup(
        self,
        balance: float,
        mode: str
    ) -> None:
        """إشعار بدء تشغيل البوت"""
        message = (
            f"⬡ <b>APEX TRADER</b>\n\n"
            f"🚀 <b>البوت يعمل!</b>\n\n"
            f"💰 الرصيد: <code>${balance:.2f}</code>\n"
            f"⚡ الوضع: <code>{mode}</code>\n"
            f"🕐 <code>"
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
            f"</code>"
        )

        await self.send(message)

    async def send_weekly_summary(
        self,
        stats: dict
    ) -> None:
        """ملخص أسبوعي"""
        message = (
            f"⬡ <b>APEX TRADER - ملخص أسبوعي</b>\n\n"
            f"📊 الصفقات: "
            f"<code>{stats.get('total_trades', 0)}</code>\n"
            f"✅ رابحة: "
            f"<code>{stats.get('winning_trades', 0)}</code>\n"
            f"💰 صافي: "
            f"<code>${stats.get('total_pnl', 0):+.2f}</code>\n"
            f"🎯 Win Rate: "
            f"<code>{stats.get('win_rate', 0):.1f}%</code>"
        )

        await self.send(message)
