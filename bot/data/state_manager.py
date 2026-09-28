# bot/data/state_manager.py - الكود المُصحَّح (كامل)
import json
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
        self.initial_bot_state: Dict[str, Any] = {}

        supabase_url = (
            getattr(getattr(config, "database", None), "supabase_url", None)
            or os.getenv("SUPABASE_URL", "")
        )
        supabase_key = (
            getattr(getattr(config, "database", None), "supabase_key", None)
            or os.getenv("SUPABASE_WRITE_KEY", "")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
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
            state_result = self.client.table("bot_state").select("*").eq("id", 1).maybe_single().execute()
            self.initial_bot_state = dict(getattr(state_result, "data", None) or {})
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
                "bot_status": "running",
                "environment": str(getattr(self.config, "environment", "testnet")),
                "heartbeat_at": now_utc,
                "last_run_at": now_utc,
                "updated_at": now_utc,
                "database_connected": True,
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
        risk_day: Optional[str] = None,
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
                updates["available_balance"] = round(balance, 2)
                updates["exchange_connected"] = True
            if daily_loss_used is not None:
                updates["daily_loss_used_usd"] = round(daily_loss_used, 2)
            if daily_realized_pnl is not None:
                updates["daily_realized_pnl"] = round(daily_realized_pnl, 2)
            if daily_loss_limit is not None:
                updates["daily_loss_limit_usd"] = round(daily_loss_limit, 2)
            if risk_day is not None:
                updates["risk_day"] = risk_day
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

    async def mark_cycle_completed(self) -> None:
        """سجل دورة مكتملة فقط بعد نجاح كل عمليات الدورة."""
        if not self.client:
            return
        try:
            now_utc = datetime.now(timezone.utc).isoformat()
            self.client.table("bot_state").upsert({
                "id": 1,
                "cycle_completed_at": now_utc,
                "updated_at": now_utc,
                "database_connected": True,
            }).execute()
        except Exception as e:
            logger.error("❌ mark_cycle_completed: {}", e)

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
                "bot_status": "stopped",
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

    def mark_trade_needs_reconciliation(self, trade: Dict[str, Any], note: str) -> bool:
        """تجميد الصفقة عندما لا يمكن مطابقة الحالة المحلية مع المنصة."""
        return self.save_trade_state({
            **trade,
            "status": "NEEDS_RECONCILIATION",
            "pnl_source": "unconfirmed",
            "reconciliation_note": note,
        })

    def record_partial_close(self, partial_data: Dict[str, Any]) -> bool:
        """Persist a partial execution separately from the parent trade."""
        if not self.client:
            logger.error("❌ partial close cannot be persisted without Supabase")
            return False
        try:
            self.client.table("partial_closes").insert(partial_data).execute()
            return True
        except Exception as e:
            logger.error("❌ record_partial_close: {}", e)
            return False

    def get_open_trades_from_db(self) -> List[Dict[str, Any]]:
        """استرجاع OPEN وNEEDS_RECONCILIATION معاً للمراجعة الآمنة."""
        if not self.client:
            raise RuntimeError("Supabase client is unavailable; state read failed closed")
        try:
            res = (
                self.client.table("trades")
                .select("*")
                .in_("status", ["OPEN", "NEEDS_RECONCILIATION"])
                .execute()
            )
            return res.data if res and hasattr(res, "data") else []
        except Exception as e:
            logger.error("❌ get_open_trades_from_db: {}", e)
            raise RuntimeError("Supabase open-trades query failed") from e

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
                entry_quantity=float(trade_dict.get("entry_quantity", 0) or 0),
                remaining_quantity=float(trade_dict.get("remaining_quantity", 0) or 0),
                entry_fee=float(trade_dict.get("entry_fee", 0)),
                exit_fee=float(trade_dict.get("exit_fee", 0)),
                # ✅ استعادة حالة Trailing/BreakEven من DB
                tp1_executed=bool(trade_dict.get("tp1_executed", False)),
                exchange_managed_protection=bool(
                    trade_dict.get("take_profit_1_algo_id")
                    or trade_dict.get("take_profit_2_algo_id")
                ),
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

    # ─── Dynamic universe ──────────────────────────────────────────────────────

    def get_active_universe_symbols(self) -> List[Dict[str, Any]]:
        """Read the currently activated universe; a failed read is fail-closed."""
        if not self.client:
            return []
        try:
            result = (
                self.client.table("universe_symbols")
                .select("symbol,rank,expires_at,snapshot_id")
                .eq("is_active", True)
                .order("rank")
                .limit(100)
                .execute()
            )
            return list(result.data or [])
        except Exception as exc:
            logger.error("❌ get_active_universe_symbols: {}", exc)
            return []

    def replace_universe_snapshot(
        self, snapshot_id: str, rows: List[Dict[str, Any]], expires_at: str
    ) -> bool:
        """Insert a complete snapshot, then atomically activate it through RPC."""
        if not self.client:
            raise RuntimeError("Supabase client is unavailable; universe persistence failed closed")
        try:
            self.client.table("universe_snapshots").insert({
                "id": snapshot_id,
                "expires_at": expires_at,
                "source": "binance_usdm",
            }).execute()
            self.client.table("universe_symbols").insert(rows).execute()
            self.client.rpc("activate_universe_snapshot", {
                "p_snapshot_id": snapshot_id,
            }).execute()
            self.client.table("bot_state").upsert({
                "id": 1,
                "active_symbols": json.dumps([row["symbol"] for row in rows]),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return True
        except Exception as exc:
            logger.error("❌ replace_universe_snapshot: {}", exc)
            raise RuntimeError("universe snapshot activation failed") from exc

    # ─── Global position slots ────────────────────────────────────────────────

    def try_reserve_position_slot(
        self, symbol: str, owner: str, reservation_id: str, max_slots: int = 3
    ) -> Optional[Dict[str, Any]]:
        """Atomically reserve one global slot; idempotent for the same symbol."""
        if not self.client:
            logger.error("❌ Cannot reserve position slot without Supabase")
            return None
        try:
            result = self.client.rpc("reserve_position_slot", {
                "p_symbol": symbol,
                "p_owner": owner,
                "p_reservation_id": reservation_id,
                "p_max_slots": int(max_slots),
            }).execute()
            data = getattr(result, "data", None) or []
            return dict(data[0]) if data else None
        except Exception as exc:
            logger.error("❌ try_reserve_position_slot {}: {}", symbol, exc)
            return None

    def bind_position_slot(self, reservation_id: str, trade_id: str) -> bool:
        if not self.client:
            return False
        try:
            result = self.client.rpc("bind_position_slot", {
                "p_reservation_id": reservation_id,
                "p_trade_id": trade_id,
            }).execute()
            return bool(getattr(result, "data", None))
        except Exception as exc:
            logger.error("❌ bind_position_slot: {}", exc)
            return False

    def release_position_slot(
        self, *, symbol: Optional[str] = None, trade_id: Optional[str] = None,
        reservation_id: Optional[str] = None,
    ) -> bool:
        if not self.client:
            return False
        try:
            result = self.client.rpc("release_position_slot", {
                "p_symbol": symbol,
                "p_trade_id": trade_id,
                "p_reservation_id": reservation_id,
            }).execute()
            return bool(getattr(result, "data", None))
        except Exception as exc:
            logger.error("❌ release_position_slot: {}", exc)
            return False
