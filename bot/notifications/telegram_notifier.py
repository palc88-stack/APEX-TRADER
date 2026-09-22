# ======================================
# APEX TRADER - Telegram Notifier
# ======================================
# نظام الإشعارات عبر Telegram
# آمن ومُنسَّق احترافياً

import asyncio
from typing import Optional
from loguru import logger
import aiohttp

from bot.config import config
from bot.core.position_manager import Position, PositionStatus


class TelegramNotifier:
    """
    مُرسِل إشعارات Telegram الاحترافي
    
    يُرسل إشعارات منسقة عن:
    - الصفقات المفتوحة والمغلقة
    - التحذيرات والطوارئ
    - التقارير اليومية
    """
    
    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"
    
    def __init__(self):
        self.token = config.telegram.bot_token
        self.chat_id = config.telegram.chat_id
        self._enabled = config.telegram.validate()
        
        if self._enabled:
            logger.info("✅ Telegram Notifier جاهز")
        else:
            logger.warning("⚠️ Telegram غير مُضبوط - الإشعارات معطّلة")
    
    async def send(
        self, 
        message: str,
        parse_mode: str = "HTML"
    ) -> bool:
        """
        إرسال رسالة لـ Telegram
        
        Args:
            message: نص الرسالة (HTML)
            parse_mode: نوع التنسيق
            
        Returns:
            bool: نجح الإرسال؟
        """
        if not self._enabled:
            logger.debug(f"📤 [محاكاة] {message[:50]}...")
            return True
        
        url = self.BASE_URL.format(token=self.token)
        
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, 
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return True
                    else:
                        error = await response.text()
                        logger.error(
                            f"❌ Telegram خطأ {response.status}: {error}"
                        )
                        return False
                        
        except asyncio.TimeoutError:
            logger.warning("⚠️ Telegram timeout")
            return False
        except Exception as e:
            logger.error(f"❌ Telegram خطأ: {e}")
            return False
    
    async def send_trade_opened(
        self,
        position: Position,
        signal = None
    ) -> None:
        """إشعار فتح صفقة"""
        direction_emoji = "🟢⬆️" if position.direction.value == "LONG" else "🔴⬇️"
        mode_emoji = {
            "SNIPER": "🎯",
            "HUNTER": "🏹",
            "FARMER": "🌾",
            "EXPLOSION": "💥"
        }
        
        mode = signal.mode.value if signal else "UNKNOWN"
        confidence = signal.confidence if signal else 0
        
        message = f"""
⬡ <b>APEX TRADER</b>

{mode_emoji.get(mode, '📊')} <b>{mode} - صفقة جديدة</b>

{direction_emoji} <b>{position.symbol}</b> {position.direction.value}

📊 <b>تفاصيل الصفقة:</b>
├ الدخول: <code>${position.entry_price:,.4f}</code>
├ حجم: <code>${position.size_usd:.2f}</code>
├ رافعة: <code>{position.leverage}x</code>
└ قيمة: <code>${position.position_value:.2f}</code>

🎯 <b>الأهداف:</b>
├ وقف خسارة: <code>${position.stop_loss:,.4f}</code>
├ هدف 1: <code>${position.take_profit_1:,.4f}</code>
└ هدف 2: <code>${position.take_profit_2:,.4f}</code>

💸 <b>العمولات:</b>
└ إجمالي: <code>${(position.entry_fee + position.exit_fee):.4f}</code>

🎯 ثقة: <code>{confidence:.1%}</code>
🏦 منصة: <code>{position.exchange.upper()}</code>
"""
        await self.send(message)
    
    async def send_trade_closed(
        self,
        position: Position,
        reason: str
    ) -> None:
        """إشعار إغلاق صفقة"""
        is_profit = position.pnl >= 0
        result_emoji = "✅" if is_profit else "❌"
        
        reason_map = {
            "tp1": "🎯 الهدف الأول",
            "tp2": "🎯🎯 الهدف الثاني",
            "stop_loss": "🛡️ وقف الخسارة",
            "trailing_stop": "🔄 Trailing Stop",
            "manual": "👤 يدوي"
        }
        
        message = f"""
⬡ <b>APEX TRADER</b>

{result_emoji} <b>صفقة مغلقة</b>

📊 <b>{position.symbol}</b> {position.direction.value}
└ السبب: {reason_map.get(reason, reason)}

💰 <b>النتيجة:</b>
├ P&L: <code>${position.pnl:+.4f}</code>
├ نسبة: <code>{position.pnl_pct:+.2f}%</code>
└ المدة: <code>{position.duration_minutes:.1f} دقيقة</code>
"""
        await self.send(message)
    
    async def send_partial_close(
        self,
        position: Position,
        price: float,
        percentage: int,
        partial_pnl: float
    ) -> None:
        """إشعار إغلاق جزئي"""
        message = f"""
⬡ <b>APEX TRADER</b>

🎯 <b>إغلاق جزئي - TP1</b>

📊 <b>{position.symbol}</b>
├ السعر: <code>${price:,.4f}</code>
├ المُغلَق: <code>{percentage}%</code>
└ ربح جزئي: <code>${partial_pnl:+.4f}</code>

🔄 الـ Trailing يحمي الباقي...
"""
        await self.send(message)
    
    async def send_daily_limit_reached(
        self, 
        loss_pct: float
    ) -> None:
        """إشعار الوصول لحد الخسارة"""
        message = f"""
⬡ <b>APEX TRADER</b>

🚨 <b>تحذير - حد الخسارة اليومية</b>

تم الوصول لحد الخسارة اليومية:
└ الخسارة: <code>{loss_pct:.1f}%</code>

⏸️ البوت متوقف حتى الغد
💤 يعود للعمل في 00:00 UTC
"""
        await self.send(message)
    
    async def send_daily_report(
        self,
        stats: dict,
        balance: float
    ) -> None:
        """التقرير اليومي"""
        win_rate = stats.get('win_rate', 0)
        win_emoji = "🟢" if win_rate >= 60 else "🟡" if win_rate >= 50 else "🔴"
        
        message = f"""
⬡ <b>APEX TRADER - تقرير يومي</b>
📅 {stats.get('date', 'اليوم')}

💰 <b>المالية:</b>
├ الرصيد: <code>${balance:.2f}</code>
├ ربح/خسارة: <code>${stats.get('net_pnl', 0):+.2f}</code>
└ نسبة: <code>{stats.get('pnl_pct', 0):+.2f}%</code>

📊 <b>الصفقات:</b>
├ الإجمالي: <code>{stats.get('total_trades', 0)}</code>
├ رابحة: <code>{stats.get('winning_trades', 0)} ✅</code>
├ خاسرة: <code>{stats.get('losing_trades', 0)} ❌</code>
└ Win Rate: {win_emoji} <code>{win_rate:.1f}%</code>

💸 رسوم: <code>${stats.get('total_fees', 0):.4f}</code>
💰 صافي: <code>${stats.get('net_pnl', 0):+.4f}</code>
"""
        await self.send(message)
    
    async def send_error(self, error_msg: str) -> None:
        """إشعار خطأ"""
        message = f"""
⬡ <b>APEX TRADER</b>

⚠️ <b>تنبيه - خطأ في النظام</b>

<code>{error_msg[:200]}</code>

🔄 سيتم المحاولة في الدورة القادمة
"""
        await self.send(message)
    
    async def send_connection_error(self) -> None:
        """إشعار انقطاع الاتصال"""
        message = """
⬡ <b>APEX TRADER</b>

🔴 <b>انقطاع الاتصال بالمنصة!</b>

جميع الأوامر المعلقة محمية بـ SL على المنصة
سيتم إعادة الاتصال في الدورة القادمة
"""
        await self.send(message)
