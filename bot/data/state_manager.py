# ======================================
# APEX TRADER - State Manager (Complete)
# ======================================
# إدارة حالة البوت الكاملة
# Supabase + Upstash Redis
# بيانات حقيقية محفوظة بأمان

import json
import redis as redis_client
from typing import Optional, List
from datetime import datetime, date, timezone
from loguru import logger
from supabase import create_client, Client

from bot.config import config
from bot.core.position_manager import Position, PositionStatus


class StateManager:
    """
    مدير الحالة المركزي

    يحفظ ويسترجع البيانات من:
    - Upstash Redis: حالة سريعة لحظية
    - Supabase PostgreSQL: سجل دائم
    """

    # مفاتيح Redis
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
        """
        تهيئة اتصالات قواعد البيانات
        """
        # === Supabase ===
        try:
            if (config.database.supabase_url and
                    config.database.supabase_key):
                self._supabase = create_client(
                    config.database.supabase_url,
                    config.database.supabase_key
                )
                # اختبار الاتصال
                self._supabase.table("bot_state").select(
                    "id"
                ).limit(1).execute()
                self._db_available = True
                logger.info("✅ Supabase متصل ويعمل")
            else:
                logger.warning("⚠️ Supabase: مفاتيح مفقودة")
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
                # اختبار الاتصال
                self._redis.ping()
                self._redis_available = True
                logger.info("✅ Redis متصل ويعمل")
            else:
                logger.warning("⚠️ Redis: URL مفقود")
        except Exception as e:
            logger.warning(f"⚠️ Redis غير متاح: {e}")
            self._redis_available = False

    # ==========================================
    # Bot State Management
    # ==========================================

    async def save_state(self, state: dict) -> bool:
        """
        حفظ حالة البوت في Redis و Supabase
        """
        state['saved_at'] = datetime.now(
            timezone.utc
        ).isoformat()

        saved_redis = self._save_to_redis(
            self.KEY_BOT_STATE,
            state,
            ttl=86400  # 24 ساعة
        )

        saved_db = await self._save_bot_state_to_db(state)

        if not saved_redis and not saved_db:
            logger.error("❌ فشل حفظ الحالة في كلا المكانين!")
            return False

        return True

    async def load_state(self) -> Optional[dict]:
        """
        تحميل حالة البوت
        Redis أولاً (أسرع) ثم Supabase
        """
        # محاولة Redis أولاً
        if self._redis_available:
            data = self._load_from_redis(self.KEY_BOT_STATE)
            if data:
                logger.debug("✅ الحالة محملة من Redis")
                return data

        # محاولة Supabase
        if self._db_available:
            return await self._load_bot_state_from_db()

        logger.warning("⚠️ لا يمكن تحميل الحالة")
        return None

    def _save_to_redis(
        self,
        key: str,
        data: dict,
        ttl: int = 3600
    ) -> bool:
        """حفظ في Redis"""
        if not self._redis_available:
            return False
        try:
            self._redis.setex(
                key,
                ttl,
                json.dumps(data, default=str)
            )
            return True
        except Exception as e:
            logger.error(f"❌ Redis save خطأ: {e}")
            return False

    def _load_from_redis(self, key: str) -> Optional[dict]:
        """تحميل من Redis"""
        if not self._redis_available:
            return None
        try:
            raw = self._redis.get(key)
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.error(f"❌ Redis load خطأ: {e}")
            return None

    async def _save_bot_state_to_db(
        self,
        state: dict
    ) -> bool:
        """حفظ الحالة في Supabase"""
        if not self._db_available:
            return False
        try:
            update_data = {
                "is_running": state.get("is_running", True),
                "is_paused": state.get("is_paused", False),
                "daily_loss": float(
                    state.get("daily_loss", 0)
                ),
                "total_trades": int(
                    state.get("total_trades", 0)
                ),
                "winning_trades": int(
                    state.get("winning_trades", 0)
                ),
                "last_run_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat()
            }

            self._supabase.table("bot_state").upsert(
                {**update_data, "id": 1},
                on_conflict="id"
            ).execute()

            return True

        except Exception as e:
            logger.error(f"❌ Supabase save state خطأ: {e}")
            return False

    async def _load_bot_state_from_db(
        self
    ) -> Optional[dict]:
        """تحميل الحالة من Supabase"""
        if not self._db_available:
            return None
        try:
            result = self._supabase.table(
                "bot_state"
            ).select("*").eq("id", 1).execute()

            if result.data:
                row = result.data[0]
                logger.debug("✅ الحالة محملة من Supabase")
                return {
                    "daily_loss": float(
                        row.get("daily_loss", 0)
                    ),
                    "total_trades": int(
                        row.get("total_trades", 0)
                    ),
                    "winning_trades": int(
                        row.get("winning_trades", 0)
                    ),
                    "is_paused": bool(
                        row.get("is_paused", False)
                    )
                }
            return None

        except Exception as e:
            logger.error(
                f"❌ Supabase load state خطأ: {e}"
            )
            return None

    # ==========================================
    # Trade Management
    # ==========================================

    async def save_trade(
        self,
        position: Position,
        signal=None
    ) -> bool:
        """
        حفظ صفقة جديدة في Supabase
        """
        if not self._db_available:
            logger.warning(
                "⚠️ Supabase غير متاح - لن تُحفظ الصفقة"
            )
            return False

        try:
            trade_data = {
                "id": position.id,
                "symbol": position.symbol,
                "direction": position.direction.value,
                "exchange": position.exchange,
                "mode": (
                    signal.mode.value
                    if signal else "UNKNOWN"
                ),
                "entry_price": float(position.entry_price),
                "stop_loss": float(position.stop_loss),
                "take_profit_1": float(
                    position.take_profit_1
                ),
                "take_profit_2": float(
                    position.take_profit_2
                ),
                "size_usd": float(position.size_usd),
                "leverage": int(position.leverage),
                "position_value": float(
                    position.position_value
                ),
                "entry_fee": float(position.entry_fee),
                "exit_fee": float(position.exit_fee),
                "total_fees": float(
                    position.entry_fee + position.exit_fee
                ),
                "confidence": float(
                    signal.confidence if signal else 0.0
                ),
                "signal_reasons": json.dumps(
                    signal.reasons if signal else []
                ),
                "is_explosion": bool(
                    signal.is_explosion if signal else False
                ),
                "status": "OPEN",
                "opened_at": (
                    position.opened_at.isoformat()
                )
            }

            self._supabase.table("trades").insert(
                trade_data
            ).execute()

            # حفظ في Redis أيضاً
            self._cache_open_position(position)

            logger.info(
                f"💾 صفقة محفوظة: {position.id} | "
                f"{position.symbol}"
            )
            return True

        except Exception as e:
            logger.error(f"❌ خطأ حفظ الصفقة: {e}")
            return False

    async def update_trade_closed(
        self,
        position: Position
    ) -> bool:
        """
        تحديث الصفقة عند الإغلاق في Supabase
        """
        if not self._db_available:
            return False

        try:
            update_data = {
                "exit_price": float(position.current_price),
                "status": position.status.value,
                "pnl": float(position.pnl),
                "pnl_pct": float(position.pnl_pct),
                "close_reason": position.status.value,
                "closed_at": (
                    position.closed_at.isoformat()
                    if position.closed_at
                    else datetime.now(timezone.utc).isoformat()
                ),
                "duration_minutes": float(
                    position.duration_minutes
                )
            }

            self._supabase.table("trades").update(
                update_data
            ).eq("id", position.id).execute()

            # تحديث الإحصاءات اليومية
            await self._update_daily_stats(position)

            # حذف من Redis
            self._remove_cached_position(position.id)

            logger.info(
                f"💾 صفقة مُحدَّثة: {position.id} | "
                f"P&L: ${position.pnl:.4f}"
            )
            return True

        except Exception as e:
            logger.error(
                f"❌ خطأ تحديث الصفقة: {e}"
            )
            return False

    def _cache_open_position(
        self,
        position: Position
    ) -> None:
        """حفظ الصفقة المفتوحة في Redis"""
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
            self._redis.setex(
                key,
                86400,
                json.dumps(pos_data)
            )
        except Exception as e:
            logger.debug(f"⚠️ Redis cache position: {e}")

    def _remove_cached_position(
        self,
        position_id: str
    ) -> None:
        """حذف الصفقة من Redis"""
        if not self._redis_available:
            return
        try:
            key = (
                f"{self.KEY_OPEN_POSITIONS}:{position_id}"
            )
            self._redis.delete(key)
        except Exception as e:
            logger.debug(f"⚠️ Redis remove position: {e}")

    # ==========================================
    # Daily Stats
    # ==========================================

    async def _update_daily_stats(
        self,
        position: Position
    ) -> None:
        """
        تحديث إحصاءات اليوم في Supabase
        """
        if not self._db_available:
            return

        try:
            today = date.today().isoformat()
            is_winner = position.pnl >= 0

            # جلب إحصاءات اليوم الحالية
            result = self._supabase.table(
                "daily_performance"
            ).select("*").eq("date", today).execute()

            if result.data:
                # تحديث
                current = result.data[0]
                update_data = {
                    "total_trades": (
                        int(current.get("total_trades", 0)) + 1
                    ),
                    "winning_trades": (
                        int(current.get("winning_trades", 0))
                        + (1 if is_winner else 0)
                    ),
                    "losing_trades": (
                        int(current.get("losing_trades", 0))
                        + (0 if is_winner else 1)
                    ),
                    "net_pnl": (
                        float(current.get("net_pnl", 0))
                        + position.pnl
                    ),
                    "total_fees": (
                        float(current.get("total_fees", 0))
                        + position.entry_fee
                        + position.exit_fee
                    ),
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat()
                }

                # حساب Win Rate
                total = update_data["total_trades"]
                if total > 0:
                    update_data["win_rate"] = round(
                        update_data["winning_trades"]
                        / total * 100, 2
                    )

                self._supabase.table(
                    "daily_performance"
                ).update(update_data).eq(
                    "date", today
                ).execute()

            else:
                # إدراج جديد
                insert_data = {
                    "date": today,
                    "total_trades": 1,
                    "winning_trades": 1 if is_winner else 0,
                    "losing_trades": 0 if is_winner else 1,
                    "win_rate": 100.0 if is_winner else 0.0,
                    "net_pnl": float(position.pnl),
                    "total_fees": (
                        float(position.entry_fee)
                        + float(position.exit_fee)
                    )
                }

                self._supabase.table(
                    "daily_performance"
                ).insert(insert_data).execute()

        except Exception as e:
            logger.error(f"❌ خطأ تحديث إحصاءات اليوم: {e}")

    async def get_daily_stats(
        self,
        target_date: Optional[date] = None
    ) -> Optional[dict]:
        """
        جلب إحصاءات يوم محدد
        """
        if not self._db_available:
            return None

        try:
            day = (target_date or date.today()).isoformat()

            result = self._supabase.table(
                "daily_performance"
            ).select("*").eq("date", day).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"❌ خطأ جلب إحصاءات {day}: {e}")
            return None

    async def get_recent_trades(
        self,
        limit: int = 20
    ) -> List[dict]:
        """
        جلب آخر الصفقات المغلقة
        """
        if not self._db_available:
            return []

        try:
            result = self._supabase.table(
                "trades"
            ).select(
                "id, symbol, direction, mode, "
                "entry_price, exit_price, pnl, "
                "pnl_pct, status, opened_at, "
                "closed_at, duration_minutes"
            ).neq(
                "status", "OPEN"
            ).order(
                "opened_at", desc=True
            ).limit(limit).execute()

            return result.data if result.data else []

        except Exception as e:
            logger.error(f"❌ خطأ جلب الصفقات: {e}")
            return []

    async def get_performance_summary(self) -> dict:
        """
        ملخص الأداء الكامل
        من Supabase مباشرة
        """
        if not self._db_available:
            return {}

        try:
            # إجمالي الصفقات
            all_trades = self._supabase.table(
                "trades"
            ).select(
                "pnl, status, pnl_pct"
            ).neq("status", "OPEN").execute()

            if not all_trades.data:
                return {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_pnl": 0.0
                }

            trades = all_trades.data
            total = len(trades)
            winners = sum(
                1 for t in trades
                if float(t.get("pnl", 0)) > 0
            )
            total_pnl = sum(
                float(t.get("pnl", 0)) for t in trades
            )

            return {
                "total_trades": total,
                "winning_trades": winners,
                "losing_trades": total - winners,
                "win_rate": round(
                    winners / total * 100, 2
                ) if total > 0 else 0.0,
                "total_pnl": round(total_pnl, 4),
                "avg_pnl": round(
                    total_pnl / total, 4
                ) if total > 0 else 0.0
            }

        except Exception as e:
            logger.error(f"❌ خطأ جلب الأداء: {e}")
            return {}

    async def record_compounding(
        self,
        compound_amount: float,
        reserved_amount: float
    ) -> None:
        """
        تسجيل عملية Compounding
        """
        if not self._db_available:
            return

        try:
            today = date.today().isoformat()

            self._supabase.table(
                "daily_performance"
            ).upsert({
                "date": today,
                "compounded_amount": round(
                    compound_amount, 4
                ),
                "reserved_amount": round(
                    reserved_amount, 4
                ),
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat()
            }, on_conflict="date").execute()

            logger.info(
                f"💰 Compounding: "
                f"${compound_amount:.4f} محفوظ"
            )

        except Exception as e:
            logger.error(
                f"❌ خطأ حفظ Compounding: {e}"
            )

    async def log_system_event(
        self,
        level: str,
        message: str,
        details: Optional[dict] = None
    ) -> None:
        """
        حفظ حدث النظام في Supabase
        """
        if not self._db_available:
            return

        try:
            self._supabase.table("system_logs").insert({
                "level": level,
                "message": message,
                "details": json.dumps(
                    details or {}, default=str
                ),
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat()
            }).execute()

        except Exception as e:
            logger.debug(f"⚠️ خطأ حفظ حدث: {e}")

    def is_healthy(self) -> dict:
        """
        فحص صحة الاتصالات
        """
        redis_ok = False
        db_ok = False

        # فحص Redis
        if self._redis_available:
            try:
                self._redis.ping()
                redis_ok = True
            except Exception:
                redis_ok = False

        # فحص Supabase
        if self._db_available:
            try:
                self._supabase.table(
                    "bot_state"
                ).select("id").limit(1).execute()
                db_ok = True
            except Exception:
                db_ok = False

        return {
            "redis": redis_ok,
            "database": db_ok,
            "overall": redis_ok or db_ok
        }
