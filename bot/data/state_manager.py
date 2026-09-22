# ======================================
# APEX TRADER - State Manager
# ======================================
# إدارة حالة البوت مع Supabase + Redis

import json
from typing import Optional
from datetime import datetime, date
from loguru import logger

from bot.config import config
from bot.core.position_manager import Position


class StateManager:
    """
    مدير الحالة المركزي
    
    يحفظ ويسترجع:
    - حالة البوت من Redis (سريع)
    - سجل الصفقات من Supabase (دائم)
    """
    
    def __init__(self):
        self._supabase = None
        self._redis = None
        self._init_connections()
    
    def _init_connections(self) -> None:
        """تهيئة اتصالات قواعد البيانات"""
        # Supabase
        try:
            if config.database.supabase_url:
                from supabase import create_client
                self._supabase = create_client(
                    config.database.supabase_url,
                    config.database.supabase_key
                )
                logger.info("✅ Supabase متصل")
        except Exception as e:
            logger.warning(f"⚠️ Supabase: {e}")
        
        # Upstash Redis
        try:
            if config.database.redis_url:
                import redis
                self._redis = redis.from_url(
                    config.database.redis_url,
                    decode_responses=True
                )
                self._redis.ping()
                logger.info("✅ Redis متصل")
        except Exception as e:
            logger.warning(f"⚠️ Redis: {e}")
    
    async def save_state(self, state: dict) -> bool:
        """حفظ الحالة في Redis"""
        try:
            if not self._redis:
                return False
            
            state['saved_at'] = datetime.utcnow().isoformat()
            self._redis.setex(
                "apex:bot:state",
                86400,  # 24 ساعة
                json.dumps(state)
            )
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ حفظ الحالة: {e}")
            return False
    
    async def load_state(self) -> Optional[dict]:
        """تحميل الحالة من Redis"""
        try:
            if not self._redis:
                return None
            
            data = self._redis.get("apex:bot:state")
            if data:
                return json.loads(data)
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ تحميل الحالة: {e}")
            return None
    
    async def save_trade(
        self, 
        position: Position,
        signal = None
    ) -> bool:
        """حفظ الصفقة في Supabase"""
        try:
            if not self._supabase:
                return False
            
            trade_data = {
                "id": position.id,
                "symbol": position.symbol,
                "direction": position.direction.value,
                "exchange": position.exchange,
                "mode": signal.mode.value if signal else "UNKNOWN",
                "entry_price": float(position.entry_price),
                "stop_loss": float(position.stop_loss),
                "take_profit_1": float(position.take_profit_1),
                "take_profit_2": float(position.take_profit_2),
                "size_usd": float(position.size_usd),
                "leverage": position.leverage,
                "position_value": float(position.position_value),
                "entry_fee": float(position.entry_fee),
                "exit_fee": float(position.exit_fee),
                "total_fees": float(
                    position.entry_fee + position.exit_fee
                ),
                "confidence": float(
                    signal.confidence if signal else 0
                ),
                "is_explosion": bool(
                    signal.is_explosion if signal else False
                ),
                "status": "OPEN",
                "opened_at": position.opened_at.isoformat()
            }
            
            self._supabase.table("trades").insert(trade_data).execute()
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ حفظ الصفقة: {e}")
            return False
    
    async def update_trade_closed(self, position: Position) -> bool:
        """تحديث الصفقة عند الإغلاق"""
        try:
            if not self._supabase:
                return False
            
            update_data = {
                "exit_price": float(position.current_price),
                "status": position.status.value,
                "pnl": float(position.pnl),
                "pnl_pct": float(position.pnl_pct),
                "close_reason": position.status.value,
                "closed_at": position.closed_at.isoformat(),
                "duration_minutes": float(position.duration_minutes)
            }
            
            self._supabase.table("trades").update(
                update_data
            ).eq("id", position.id).execute()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ تحديث الصفقة: {e}")
            return False
    
    async def record_compounding(
        self,
        compound_amount: float,
        reserved_amount: float
    ) -> None:
        """تسجيل عمليات Compounding"""
        try:
            if not self._supabase:
                return
            
            today = date.today().isoformat()
            
            self._supabase.table("daily_performance").upsert({
                "date": today,
                "compounded_amount": compound_amount,
                "reserved_amount": reserved_amount,
                "updated_at": datetime.utcnow().isoformat()
            }, on_conflict="date").execute()
            
        except Exception as e:
            logger.error(f"❌ خطأ تسجيل Compounding: {e}")
