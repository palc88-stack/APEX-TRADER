# bot/data/state_manager.py - الكود المُصحَّح (كامل)
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from supabase import create_client, Client

from bot.core.position_manager import Position, PositionStatus
from bot.signals.signal_engine import TradeDirection


class StateManager:
    """
    مدير الحالة الكامل لـ Apex Trader.
    يتولى: Supabase read/write، Heartbeat، استعادة الصفقات.
    """

    def __init__(self, config: Optional[Any] = None):
        self.config = config

        supabase_url = (
            getattr(getattr(config, "database", None), "supabase_url", None)
            or os.getenv("SUPABASE_URL", "")
        )
        supabase_key = (
            getattr(getattr(config, "database", None), "supabase_key", None)
            or os.getenv("SUPABASE_KEY", "")
        )

        self.client: Optional[Client] = None
        if supabase_url and supabase_key:
            try:
                self.client = create_client(supabase_url, supabase_key)
                # ✅ اختبار اتصال حقيقي فوراً — لا نكتفي بإنشاء client
                try:
                    test_res = self.client.table("bot_state").select("*").limit(1).execute()
                    logger.info("✅ StateManager: Supabase متصل (جرب اتصال ناجح)")
                except Exception as conn_err:
                    logger.warning(
                        "⚠️ StateManager: client أنشئ لكن الربط الفعلي فشل: {} — "
                        "قد تفشل عمليات الكتابة لاحقاً",
                        conn_err
                    )
            except Exception as e:
                logger.error("❌ Supabase connection failed: {}", e)
        else:
            logger.warning("⚠️ Supabase غير مضبوط - وضع محلي")

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def load_initial_state(self) -> None:
        """استعادة الصفقات المفتوحة من قاعدة البيانات عند البدء."""
        if not self.client:
            return
        try:
            open_trades = self.get_open_trades_from_db()
            logger.info(
                "✅ تم استعادة {} صفقة مفتوحة من قاعدة البيانات.",
                len(open_trades)
            )
        except Exception as e:
            logger.error("❌ load_initial_state: {}", e)

    async def update_heartbeat(self) -> None:
        """
        ✅ كتابة Heartbeat عبر StateManager (لا يتجاوزه main.py).
        يكتب في جدول bot_state (الاسم الصحيح في schema.sql).
        """
        if not self.client:
            return
        try:
            now_utc = datetime.now(timezone.utc).isoformat()
            # ✅ استخدام upsert لضمان وجود الصف حتى لو لم يُدرج مسبقاً
            self.client.table("bot_state").upsert({
                "id": 1,
                "is_running": True,
                "last_run_at": now_utc,
                "updated_at": now_utc,
            }).execute()
            logger.info("💓 Heartbeat مُكتوبة: {} | is_running=true", now_utc)
        except Exception as e:
            logger.error("❌ update_heartbeat: {}", e)

    async def update_bot_status(
        self,
        balance: Optional[float] = None,
        daily_loss_used: Optional[float] = None,
        daily_realized_pnl: Optional[float] = None,
        daily_loss_limit: Optional[float] = None,
    ) -> None:
        """
        تحديث الحالة المالية للبوت — يُستخدم من main.py.
        """
        if not self.client:
            return
        try:
            updates: Dict[str, Any] = {
                "id": 1,  # ✅ إضافة id لضمان upsert يعمل حتى بدون INSERT مسبق
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if balance is not None:
                updates["current_balance"] = round(balance, 2)
            if daily_loss_used is not None:
                updates["daily_loss_used_usd"] = round(daily_loss_used, 2)
            if daily_realized_pnl is not None:
                updates["daily_realized_pnl"] = round(daily_realized_pnl, 2)
            if daily_loss_limit is not None:
                updates["daily_loss_limit_usd"] = round(daily_loss_limit, 2)
            # ✅ استخدام upsert بدلاً من update — يضمن وجود الصف
            self.client.table("bot_state").upsert(updates).execute()
            logger.info(
                "📊 Bot status مُحدَّث: balance={}, loss_used={}, pnl={}",
                updates.get("current_balance"),
                updates.get("daily_loss_used_usd"),
                updates.get("daily_realized_pnl")
            )
        except Exception as e:
            logger.error("❌ update_bot_status: {}", e)

    async def mark_bot_stopped(self) -> None:
        """تسجيل إيقاف البوت في قاعدة البيانات."""
        if not self.client:
            return
        try:
            now_utc = datetime.now(timezone.utc).isoformat()
            # ✅ استخدام upsert بدلاً من update
            self.client.table("bot_state").upsert({
                "id": 1,
                "is_running": False,
                "updated_at": now_utc
            }).execute()
            logger.info("🛑 Bot marked as stopped in DB")
        except Exception as e:
            logger.error("❌ mark_bot_stopped: {}", e)

    # ─── Trades ───────────────────────────────────────────────────────────────

    def save_trade_state(self, trade_data: Dict[str, Any]) -> bool:
        """حفظ أو تحديث صفقة في Supabase."""
        if not self.client:
            logger.debug("ℹ️ Supabase غير مفعّل، تخطي الحفظ.")
            return False
        try:
            self.client.table("trades").upsert(trade_data).execute()
            logger.info(
                "✅ تم حفظ الصفقة: {}", trade_data.get("symbol")
            )
            return True
        except Exception as e:
            logger.error("❌ save_trade_state: {}", e)
            return False

    def get_open_trades_from_db(self) -> List[Dict[str, Any]]:
        """استرجاع الصفقات المفتوحة من Supabase."""
        if not self.client:
            return []
        try:
            res = (
                self.client.table("trades")
                .select("*")
                .eq("status", "OPEN")
                .execute()
            )
            return res.data if res and hasattr(res, "data") else []
        except Exception as e:
            logger.error("❌ get_open_trades_from_db: {}", e)
            return []

    def reconstruct_position(
        self, trade_dict: Dict[str, Any]
    ) -> Optional[Position]:
        """
        ✅ دالة مفقودة - تحوّل dict من Supabase إلى Position object.
        ضرورية لإعادة تفعيل Trailing Stop و Break Even بعد إعادة تشغيل البوت.
        """
        try:
            direction_str = trade_dict.get("direction", "LONG").upper()
            direction = (
                TradeDirection.LONG
                if direction_str == "LONG"
                else TradeDirection.SHORT
            )

            pos = Position(
                id=str(trade_dict.get("id", "")),
                symbol=str(trade_dict.get("symbol", "")),
                direction=direction,
                exchange=str(trade_dict.get("exchange", "binance")),
                entry_price=float(trade_dict.get("entry_price", 0)),
                current_price=float(trade_dict.get("entry_price", 0)),
                stop_loss=float(trade_dict.get("stop_loss", 0)),
                take_profit_1=float(trade_dict.get("take_profit_1", 0)),
                take_profit_2=float(trade_dict.get("take_profit_2", 0)),
                size_usd=float(trade_dict.get("size_usd", 0)),
                leverage=int(trade_dict.get("leverage", 10)),
                entry_fee=float(trade_dict.get("entry_fee", 0)),
                exit_fee=float(trade_dict.get("exit_fee", 0)),
                # ✅ استعادة حالة Trailing/BreakEven من DB
                tp1_executed=bool(trade_dict.get("tp1_executed", False)),
                trailing_active=bool(trade_dict.get("trailing_active", False)),
                trailing_stop=float(trade_dict.get("trailing_stop", 0)),
                breakeven_set=bool(trade_dict.get("breakeven_set", False)),
                highest_price=float(
                    trade_dict.get("highest_price", 0)
                    or trade_dict.get("entry_price", 0)
                ),
                lowest_price=float(
                    trade_dict.get("lowest_price", 0)
                    or trade_dict.get("entry_price", 0)
                ),
                status=PositionStatus.OPEN,
            )
            return pos
        except Exception as e:
            logger.error(
                "❌ reconstruct_position فشل لـ {}: {}",
                trade_dict.get("id"), e
            )
            return None

    # ─── Pending Signals ( webhook ↔ bot) ────────────────────────────────────────────

    def get_pending_signals(self) -> List[Dict[str, Any]]:
        """استرجاع جميع الإشارات المعلقة من Supabase (من Cloudflare Worker)"""
        if not self.client:
            return []
        try:
            res = (
                self.client.table("pending_signals")
                .select("*")
                .eq("status", "pending")
                .order("created_at", ascending=True)
                .execute()
            )
            return res.data if res and hasattr(res, "data") else []
        except Exception as e:
            logger.error("❌ get_pending_signals: {}", e)
            return []

    def mark_signal_processed(self, signal_id: int) -> bool:
        """وضع علامة Processed على الإشارة بعد تنفيذها"""
        if not self.client:
            return False
        try:
            self.client.table("pending_signals").update({
                "status": "processed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", signal_id).execute()
            logger.info("✅ تم وضع علامة Processed على pending_signal #{}", signal_id)
            return True
        except Exception as e:
            logger.error("❌ mark_signal_processed: {}", e)
            return False
