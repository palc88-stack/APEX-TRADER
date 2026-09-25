import json
import redis as redis_client
from typing import Optional, List
from datetime import datetime, date, timezone
from loguru import logger
from supabase import create_client, Client

from bot.config import config
from bot.core.position_manager import Position, PositionStatus
from bot.signals.signal_engine import TradeDirection


class StateManager:
    """
    مدير الحالة المركزي لبوت التداول APEX TRADER.
    يقوم بإدارة وتحفيظ البيانات بين Upstash Redis و Supabase PostgreSQL.
    """

    KEY_BOT_STATE = "apex:bot:state"
    KEY_DAILY_STATS = "apex:daily:stats"
    KEY_OPEN_POSITIONS = "apex:positions:open"

    def __init__(self):
        self._supabase: Optional[Client] = None
        self._redis: Optional[redis_client.Redis] = None
        self._db_available: bool = False
        self._redis_available: bool = False
        self._init_connections()

    def _init_connections(self) -> None:
        """تهيئة واختبار اتصالات قواعد البيانات."""
        # === Supabase ===
        try:
            if config.database.supabase_url and config.database.supabase_key:
                self._supabase = create_client(
                    config.database.supabase_url,
                    config.database.supabase_key
                )
                self._supabase.table("bot_state").select("id").limit(1).execute()
                self._db_available = True
                logger.info("✅ Supabase متصل ويعمل بنجاح")
            else:
                logger.warning("⚠️ Supabase: البيانات والمفاتيح غير مكتملة في الإعدادات")
        except Exception as e:
            logger.warning(f"⚠️ Supabase غير متاح: {e}")
            self._db_available = False

        # === Upstash Redis ===
        try:
            if config.database.redis_url:
                self._redis = redis_client.from_url(
                    config.database.redis_url,
                    password=config.database.redis_token,
                    decode_responses=True,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                self._redis.ping()
                self._redis_available = True
                logger.info("✅ Redis متصل ويعمل بنجاح")
            else:
                logger.warning("⚠️ Redis: رابط الاتصال مفقود")
        except Exception as e:
            logger.warning(f"⚠️ Redis غير متاح: {e}")
            self._redis_available = False

    # ==========================================
    # 1. إدارة حالة البوت العامة (Bot State)
    # ==========================================

    async def save_state(self, state: dict) -> bool:
        """حفظ حالة البوت العامة في Redis و Supabase."""
        state['saved_at'] = datetime.now(timezone.utc).isoformat()
        saved_redis = self._save_to_redis(self.KEY_BOT_STATE, state, ttl=86400)
        saved_db = await self._save_bot_state_to_db(state)

        if not saved_redis and not saved_db:
            logger.error("❌ فشل حفظ حالة البوت في كلا المصدرين!")
            return False

        return True

    async def load_state(self) -> Optional[dict]:
        """تحميل حالة البوت (محاولة القراءة من Redis أولاً ثم Supabase)."""
        if self._redis_available:
            data = self._load_from_redis(self.KEY_BOT_STATE)
            if data:
                logger.debug("✅ تم تحميل حالة البوت من ذاكرة Redis")
                return data

        if self._db_available:
            return await self._load_bot_state_from_db()

        logger.warning("⚠️ تعذر تحميل حالة البوت من Redis و Supabase")
        return None

    def _save_to_redis(self, key: str, data: dict, ttl: int = 3600) -> bool:
        if not self._redis_available:
            return False
        try:
            self._redis.setex(key, ttl, json.dumps(data, default=str))
            return True
        except Exception as e:
            logger.error(f"❌ خطأ عند الحفظ في Redis ({key}): {e}")
            return False

    def _load_from_redis(self, key: str) -> Optional[dict]:
        if not self._redis_available:
            return None
        try:
            raw = self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.error(f"❌ خطأ عند القراءة من Redis ({key}): {e}")
            return None

    async def _save_bot_state_to_db(self, state: dict) -> bool:
        if not self._db_available:
            return False
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            update_data = {
                "id": 1,
                "is_running": state.get("is_running", True),
                "is_paused": state.get("is_paused", False),
                "daily_loss": float(state.get("daily_loss", 0)),
                "total_trades": int(state.get("total_trades", 0)),
                "winning_trades": int(state.get("winning_trades", 0)),
                "last_run_at": now_iso,
                "updated_at": now_iso
            }
            self._supabase.table("bot_state").upsert(update_data, on_conflict="id").execute()
            return True
        except Exception as e:
            logger.error(f"❌ خطأ حفظ حالة البوت في Supabase: {e}")
            return False

    async def _load_bot_state_from_db(self) -> Optional[dict]:
        if not self._db_available:
            return None
        try:
            result = self._supabase.table("bot_state").select("*").eq("id", 1).execute()
            if result.data:
                row = result.data[0]
                logger.debug("✅ تم تحميل حالة البوت من Supabase")
                return {
                    "daily_loss": float(row.get("daily_loss", 0)),
                    "total_trades": int(row.get("total_trades", 0)),
                    "winning_trades": int(row.get("winning_trades", 0)),
                    "is_paused": bool(row.get("is_paused", False))
                }
            return None
        except Exception as e:
            logger.error(f"❌ خطأ قراءة حالة البوت من Supabase: {e}")
            return None

    # ==========================================
    # 2. إدارة الصفقات واسترجاع الحالة (Positions)
    # ==========================================

    async def get_open_positions_from_db(self) -> List[Position]:
        """استرجاع الصفقات المفتوحة من Supabase لإعادة إعمار الذاكرة عند بدء التشغيل."""
        if not self._db_available:
            logger.warning("⚠️ Supabase غير متاح - يتعذر استرجاع الصفقات المفتوحة")
            return []

        try:
            result = self._supabase.table("trades").select("*").eq("status", "OPEN").execute()
            positions: List[Position] = []

            for row in (result.data or []):
                try:
                    opened_at_raw = row.get("opened_at")
                    if opened_at_raw:
                        opened_at = datetime.fromisoformat(str(opened_at_raw).replace("Z", "+00:00"))
                    else:
                        opened_at = datetime.now(timezone.utc)

                    position = Position(
                        id=row["id"],
                        symbol=row["symbol"],
                        direction=TradeDirection(row["direction"]),
                        exchange=row.get("exchange", "binance"),
                        entry_price=float(row["entry_price"]),
                        current_price=float(row["entry_price"]),
                        stop_loss=float(row.get("stop_loss") or 0),
                        take_profit_1=float(row.get("take_profit_1") or 0),
                        take_profit_2=float(row.get("take_profit_2") or 0),
                        size_usd=float(row["size_usd"]),
                        leverage=int(row["leverage"]),
                        entry_fee=float(row.get("entry_fee") or 0),
                        exit_fee=float(row.get("exit_fee") or 0),
                        opened_at=opened_at,
                    )

                    # استرجاع خصائص التتبع والمخاطرة للصفقة
                    position.tp1_executed = bool(row.get("tp1_executed", False))
                    position.trailing_active = bool(row.get("trailing_active", False))
                    position.trailing_stop = float(row.get("trailing_stop") or 0)
                    position.breakeven_set = bool(row.get("breakeven_set", False))

                    saved_high = float(row.get("highest_price") or 0)
                    saved_low = float(row.get("lowest_price") or 0)
                    position.highest_price = saved_high if saved_high > 0 else position.entry_price
                    position.lowest_price = saved_low if saved_low > 0 else position.entry_price

                    positions.append(position)
                except Exception as row_error:
                    logger.error(f"❌ خطأ إعادة بناء الصفقة {row.get('id', '?')}: {row_error}")

            if positions:
                logger.info(f"🔄 تم استرجاع {len(positions)} صفقة مفتوحة من قاعدة البيانات")

            return positions
        except Exception as e:
            logger.error(f"❌ خطأ جلب الصفقات المفتوحة: {e}")
            return []

    async def save_trade(self, position: Position, signal=None) -> bool:
        """حفظ صفقة جديدة في Supabase وذاكرة الكاش."""
        if not self._db_available:
            logger.warning("⚠️ Supabase غير متاح - لم يتم تسجيل الصفقة جديداً")
            return False

        try:
            trade_data = {
                "id": position.id,
                "symbol": position.symbol,
                "direction": position.direction.value,
                "exchange": position.exchange,
                "mode": signal.mode.value if signal and hasattr(signal, 'mode') else "UNKNOWN",
                "entry_price": float(position.entry_price),
                "stop_loss": float(position.stop_loss),
                "take_profit_1": float(position.take_profit_1),
                "take_profit_2": float(position.take_profit_2),
                "size_usd": float(position.size_usd),
                "leverage": int(position.leverage),
                "position_value": float(position.position_value),
                "entry_fee": float(position.entry_fee),
                "exit_fee": float(position.exit_fee),
                "total_fees": float(position.entry_fee + position.exit_fee),
                "confidence": float(getattr(signal, 'confidence', 0.0)),
                "signal_reasons": json.dumps(getattr(signal, 'reasons', [])),
                "is_explosion": bool(getattr(signal, 'is_explosion', False)),
                "status": "OPEN",
                "opened_at": position.opened_at.isoformat(),
                "tp1_executed": False,
                "trailing_active": False,
                "trailing_stop": 0,
                "breakeven_set": False,
                "highest_price": float(position.entry_price),
                "lowest_price": float(position.entry_price),
            }

            self._supabase.table("trades").insert(trade_data).execute()
            self._cache_open_position(position)
            logger.info(f"💾 تم حفظ الصفقة بنجاح: {position.id} | {position.symbol}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ حفظ الصفقة الجديدة: {e}")
            return False

    async def update_position_state(self, position: Position) -> bool:
        """تحديث بيانات الصفقة أثناء عملها (Trailing, Break Even, TP1, Size)."""
        if not self._db_available:
            return False

        try:
            update_data = {
                "size_usd": float(position.size_usd),
                "stop_loss": float(position.stop_loss),
                "tp1_executed": bool(position.tp1_executed),
                "trailing_active": bool(position.trailing_active),
                "trailing_stop": float(position.trailing_stop or 0),
                "breakeven_set": bool(position.breakeven_set),
                "highest_price": float(position.highest_price),
                "lowest_price": float(position.lowest_price),
            }

            self._supabase.table("trades").update(update_data).eq("id", position.id).execute()
            return True
        except Exception as e:
            logger.error(f"❌ خطأ تحديث حالة الصفقة {position.id}: {e}")
            return False

    async def update_trade_closed(self, position: Position) -> bool:
        """تحديث بيانات الصفقة عند الإغلاق النهائي وتحديث الإحصائيات اليومية."""
        if not self._db_available:
            return False

        try:
            closed_at_val = (
                position.closed_at.isoformat()
                if getattr(position, 'closed_at', None)
                else datetime.now(timezone.utc).isoformat()
            )
            update_data = {
                "exit_price": float(position.current_price),
                "status": position.status.value,
                "pnl": float(position.pnl),
                "pnl_pct": float(position.pnl_pct),
                "close_reason": position.status.value,
                "closed_at": closed_at_val,
                "duration_minutes": float(position.duration_minutes)
            }

            self._supabase.table("trades").update(update_data).eq("id", position.id).execute()
            await self._update_daily_stats(position)
            self._remove_cached_position(position.id)

            logger.info(f"💾 تم تحديث إغلاق الصفقة: {position.id} | P&L: ${position.pnl:.4f}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ تحديث إغلاق الصفقة: {e}")
            return False

    def _cache_open_position(self, position: Position) -> None:
        if not self._redis_available:
            return
        try:
            pos_data = {
                "id": position.id,
                "symbol": position.symbol,
                "direction": position.direction.value,
                "entry_price": float(position.entry_price),
                "stop_loss": float(position.stop_loss),
                "size_usd": float(position.size_usd),
                "leverage": position.leverage,
                "opened_at": position.opened_at.isoformat()
            }
            key = f"{self.KEY_OPEN_POSITIONS}:{position.id}"
            self._redis.setex(key, 86400, json.dumps(pos_data))
        except Exception as e:
            logger.debug(f"⚠️ خطأ حفظ الصفقة المفتوحة في Redis: {e}")

    def _remove_cached_position(self, position_id: str) -> None:
        if not self._redis_available:
            return
        try:
            key = f"{self.KEY_OPEN_POSITIONS}:{position_id}"
            self._redis.delete(key)
        except Exception as e:
            logger.debug(f"⚠️ خطأ حذف الصفقة من Redis: {e}")

    # ==========================================
    # 3. إحصائيات الأداء والـ Compounding
    # ==========================================

    async def _update_daily_stats(self, position: Position) -> None:
        if not self._db_available:
            return

        try:
            today = date.today().isoformat()
            is_winner = position.pnl >= 0

            result = self._supabase.table("daily_performance").select("*").eq("date", today).execute()

            if result.data:
                current = result.data[0]
                total_trades = int(current.get("total_trades", 0)) + 1
                winning_trades = int(current.get("winning_trades", 0)) + (1 if is_winner else 0)
                losing_trades = int(current.get("losing_trades", 0)) + (0 if is_winner else 1)

                update_data = {
                    "total_trades": total_trades,
                    "winning_trades": winning_trades,
                    "losing_trades": losing_trades,
                    "net_pnl": float(current.get("net_pnl", 0)) + position.pnl,
                    "total_fees": float(current.get("total_fees", 0)) + position.entry_fee + position.exit_fee,
                    "win_rate": round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0.0,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }

                self._supabase.table("daily_performance").update(update_data).eq("date", today).execute()
            else:
                insert_data = {
                    "date": today,
                    "total_trades": 1,
                    "winning_trades": 1 if is_winner else 0,
                    "losing_trades": 0 if is_winner else 1,
                    "win_rate": 100.0 if is_winner else 0.0,
                    "net_pnl": float(position.pnl),
                    "total_fees": float(position.entry_fee + position.exit_fee)
                }
                self._supabase.table("daily_performance").insert(insert_data).execute()
        except Exception as e:
            logger.error(f"❌ خطأ تحديث الإحصائيات اليومية: {e}")

    async def get_daily_stats(self, target_date: Optional[date] = None) -> Optional[dict]:
        if not self._db_available:
            return None
        day = (target_date or date.today()).isoformat()
        try:
            result = self._supabase.table("daily_performance").select("*").eq("date", day).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"❌ خطأ جلب الإحصائيات اليومية لـ {day}: {e}")
            return None

    async def get_recent_trades(self, limit: int = 20) -> List[dict]:
        if not self._db_available:
            return []
        try:
            result = self._supabase.table("trades").select(
                "id, symbol, direction, mode, entry_price, exit_price, pnl, pnl_pct, status, opened_at, closed_at, duration_minutes"
            ).neq("status", "OPEN").order("opened_at", desc=True).limit(limit).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"❌ خطأ جلب الصفقات المغلقة المكتملة: {e}")
            return []

    async def get_performance_summary(self) -> dict:
        if not self._db_available:
            return {}
        try:
            all_trades = self._supabase.table("trades").select("pnl, status, pnl_pct").neq("status", "OPEN").execute()
            if not all_trades.data:
                return {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_pnl": 0.0
                }

            trades = all_trades.data
            total = len(trades)
            winners = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
            total_pnl = sum(float(t.get("pnl", 0)) for t in trades)

            return {
                "total_trades": total,
                "winning_trades": winners,
                "losing_trades": total - winners,
                "win_rate": round(winners / total * 100, 2) if total > 0 else 0.0,
                "total_pnl": round(total_pnl, 4),
                "avg_pnl": round(total_pnl / total, 4) if total > 0 else 0.0
            }
        except Exception as e:
            logger.error(f"❌ خطأ جلب الملخص الشامل للأداء: {e}")
            return {}

    async def record_compounding(self, compound_amount: float, reserved_amount: float) -> None:
        if not self._db_available:
            return
        try:
            today = date.today().isoformat()
            self._supabase.table("daily_performance").upsert({
                "date": today,
                "compounded_amount": round(compound_amount, 4),
                "reserved_amount": round(reserved_amount, 4),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, on_conflict="date").execute()
            logger.info(f"💰 Compounding: ${compound_amount:.4f} تم حفظه في سجلات الأداء")
        except Exception as e:
            logger.error(f"❌ خطأ حفظ بيانات Compounding: {e}")

    async def log_system_event(self, level: str, message: str, details: Optional[dict] = None) -> None:
        if not self._db_available:
            return
        try:
            self._supabase.table("system_logs").insert({
                "level": level,
                "message": message,
                "details": json.dumps(details or {}, default=str),
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            logger.debug(f"⚠️ خطأ تسجيل حدث النظام: {e}")

    # ==========================================
    # 4. فحص الجاهزية والاتصال (Health Check)
    # ==========================================

    def is_healthy(self) -> dict:
        """فحص جاهزية الاتصالات وحالتها اللحظية."""
        redis_ok = False
        db_ok = False

        if self._redis_available and self._redis is not None:
            try:
                self._redis.ping()
                redis_ok = True
            except Exception:
                redis_ok = False

        if self._db_available and self._supabase is not None:
            try:
                self._supabase.table("bot_state").select("id").limit(1).execute()
                db_ok = True
            except Exception:
                db_ok = False

        return {
            "redis": redis_ok,
            "database": db_ok,
            "overall": redis_ok or db_ok
        }
