# bot/main.py - Binance Testnet polling trader

import asyncio
import hashlib
import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any


from bot.config import Config
from bot.data.market_data import MarketDataManager
from bot.core.exchange import ExchangeManager
from bot.signals.signal_engine import SignalEngine
from bot.signals.indicators import IndicatorCalculator
from bot.signals.filters import SignalFilters
from bot.strategies.explosion import ExplosionDetector
from bot.strategies.scalping import ScalpingStrategy
from bot.core.risk_manager import RiskManager
from bot.core.fee_calculator import FeeCalculator
from bot.core.position_manager import PositionManager
from bot.data.state_manager import StateManager
from bot.data.universe_manager import UniverseManager
from bot.notifications.telegram_notifier import TelegramNotifier
from bot.learning.shadow import (
    build_shadow_observation,
    recommend_shadow_action,
    update_shadow_outcome,
)
from bot.learning.committee_shadow import build_committee_assessment

logger = logging.getLogger("ApexTrader.Main")


class ApexTraderBot:
    def __init__(self):
        self.config = Config()

        self.exchange = ExchangeManager(self.config)
        self.market_data = MarketDataManager(exchange_source=self.exchange)

        self.indicators = IndicatorCalculator(self.config)
        self.filters = SignalFilters(self.config)
        self.explosion_detector = ExplosionDetector()
        self.scalping_strategy = ScalpingStrategy(self.config)
        self.signal_engine = SignalEngine(self.config)

        self.risk_manager = RiskManager(self.config)
        self.fee_calculator = FeeCalculator(self.config)
        self.position_manager = PositionManager()

        self.state_manager = StateManager(self.config)
        self.universe_manager = UniverseManager(
            self.exchange, self.state_manager, self.config
        )
        self.telegram = TelegramNotifier()
        # ✅ تتبع الحالة المالية اليومية
        self._daily_loss_used = 0.0
        self._daily_realized_pnl = 0.0
        self._risk_day = datetime.now(timezone.utc).date().isoformat()
        self._current_balance = 0.0
        self._reconciliation_blocked_symbols: set[str] = set()
        self._slot_owner = f"apex-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self._last_symbol_scan_at = 0.0

    # ✅ إصلاح: Heartbeat عبر StateManager
    async def start_heartbeat_loop(self, interval_seconds: int = 10):
        """إرسال نبضات دورية عبر StateManager - لا كتابة مباشرة لـ Supabase."""
        logger.info("💗 بدء حلقة Heartbeat...")
        while True:
            try:
                if self.state_manager.lease_acquired:
                    self.state_manager.renew_execution_lease()
                await self.state_manager.update_heartbeat()
                # ✅ تحديث الحالة المالية كل دورة
                try:
                    balance = await self.exchange.get_balance()
                    if balance <= 0:
                        raise RuntimeError("invalid or unavailable exchange balance")
                    self._current_balance = balance
                    self._daily_loss_limit = (
                        float(self.config.risk.max_daily_loss_pct or 4.0) / 100.0
                    ) * balance
                    await self.state_manager.update_bot_status(
                        balance=balance,
                        daily_loss_used=self._daily_loss_used,
                        daily_realized_pnl=self._daily_realized_pnl,
                        daily_loss_limit=self._daily_loss_limit,
                        risk_day=self._risk_day,
                    )
                except Exception as e:
                    logger.debug(f"⚠️ لا يمكن جلب الرصيد للـ heartbeat: {e}")
            except Exception as e:
                logger.error(f"⚠️ فشل Heartbeat: {e}")
            await asyncio.sleep(interval_seconds)

    async def initialize(self) -> None:
        logger.info("Initializing ApexTrader...")
        await self.state_manager.load_initial_state()
        confirmed_metrics = self.state_manager.get_daily_confirmed_metrics()
        stored_day = str(self.state_manager.initial_bot_state.get("risk_day") or "")
        if stored_day == self._risk_day:
            self._daily_loss_used = float(
                self.state_manager.initial_bot_state.get("daily_loss_used_usd") or 0.0
            )
            self._daily_realized_pnl = float(
                self.state_manager.initial_bot_state.get("daily_realized_pnl") or 0.0
            )
        else:
            self._daily_loss_used = 0.0
            self._daily_realized_pnl = 0.0
        if confirmed_metrics is not None:
            self._daily_loss_used = confirmed_metrics["loss_used"]
            self._daily_realized_pnl = confirmed_metrics["realized_pnl"]
            logger.info(
                "📊 Daily risk state synchronized from confirmed trades: loss_used={}, pnl={}",
                self._daily_loss_used,
                self._daily_realized_pnl,
            )
        await self._reconcile_before_trading()
        for trade in self.state_manager.get_open_trades_from_db():
            if trade.get("status") != "OPEN" or not trade.get("symbol"):
                continue
            slot = self.state_manager.try_reserve_position_slot(
                str(trade["symbol"]), self._slot_owner,
                str(trade.get("entry_order_id") or trade.get("id")),
                max_slots=self.config.trading.max_open_positions,
            )
            if not slot:
                raise RuntimeError("open positions exceed the global position-slot limit")
            reservation_id = str(slot.get("reservation_id") or "")
            trade_id = str(trade.get("entry_order_id") or trade.get("id") or "")
            if reservation_id and trade_id and not slot.get("trade_id"):
                self.state_manager.bind_position_slot(reservation_id, trade_id)
        await self.universe_manager.refresh_if_due(force=True)

        if self.config.universe_refresh_only:
            logger.info(
                "✅ Universe refresh-only mode completed; no balance check, signal evaluation, or order path will run"
            )
            return

        # ✅ فحص اتصال Supabase - إذا فشل، نكتب في واجهة مستقلة
        balance = await self.exchange.get_balance()
        if balance <= 0:
            raise RuntimeError("cannot initialize without a valid exchange balance")
        self._current_balance = balance
        self._daily_loss_limit = (
            float(self.config.risk.max_daily_loss_pct or 4.0) / 100.0
            * balance
        )

        # كتابة الحالة الأولية
        await self.state_manager.update_bot_status(
            balance=balance,
            daily_loss_used=self._daily_loss_used,
            daily_realized_pnl=self._daily_realized_pnl,
            daily_loss_limit=self._daily_loss_limit,
            risk_day=self._risk_day,
        )

        if self.state_manager.client is None:
            raise RuntimeError("Supabase is required for safe state persistence")

        await self.telegram.send_startup(
            balance=balance,
            mode=str(self.config.active_mode)
        )

    async def _reconcile_before_trading(self, *, fail_closed: bool = True) -> bool:
        """Refresh exchange/DB consistency before every cycle; block entries on uncertainty."""
        try:
            local = self.state_manager.get_open_trades_from_db()
        except Exception as exc:
            self._reconciliation_blocked_symbols = set()
            if fail_closed:
                raise RuntimeError("cannot read local trades for reconciliation") from exc
            logger.error("❌ Cannot read local trades; skipping trading cycle: %s", exc)
            return False

        self._reconciliation_blocked_symbols = {
            str(trade.get("symbol")) for trade in local
            if trade.get("status") == "NEEDS_RECONCILIATION" and trade.get("symbol")
        }
        result = await self.exchange.get_all_open_positions_result()
        if not result.ok:
            self._reconciliation_blocked_symbols.update(
                str(trade.get("symbol")) for trade in local if trade.get("symbol")
            )
            if fail_closed:
                raise RuntimeError("cannot reconcile exchange positions: " + str(result.error))
            logger.error("❌ Exchange positions unavailable; skipping entries this cycle: %s", result.error)
            return False

        local_open = {
            str(trade.get("symbol")): trade for trade in local
            if trade.get("status") == "OPEN" and trade.get("symbol")
        }
        exchange_positions = {
            str(position.get("symbol")): position for position in result.data
            if position.get("symbol")
        }
        exchange_symbols = set(exchange_positions)
        self._release_stale_position_slots(
            local_trades=local,
            exchange_symbols=exchange_symbols,
        )
        unresolved_persistence: set[str] = set()
        for symbol, trade in local_open.items():
            position = exchange_positions.get(symbol)
            if position is None:
                saved = self.state_manager.mark_trade_needs_reconciliation(
                    trade,
                    "local OPEN trade missing from exchange during periodic reconciliation",
                )
                self._reconciliation_blocked_symbols.add(symbol)
                if not saved:
                    unresolved_persistence.add(symbol)
                continue

            local_quantity = float(
                trade.get("remaining_quantity") or trade.get("entry_quantity") or 0.0
            )
            info = position.get("info") or {}
            exchange_quantity = abs(float(
                position.get("contracts") or position.get("positionAmt")
                or info.get("positionAmt") or 0.0
            ))
            tolerance = max(1e-8, local_quantity * 0.001)
            if local_quantity > 0 and abs(local_quantity - exchange_quantity) > tolerance:
                saved = self.state_manager.mark_trade_needs_reconciliation(
                    trade,
                    "local/exchange quantity mismatch during periodic reconciliation",
                )
                self._reconciliation_blocked_symbols.add(symbol)
                if not saved:
                    unresolved_persistence.add(symbol)

            close_orders = self.state_manager.get_reconciliation_close_orders(
                str(trade.get("id") or trade.get("entry_order_id") or "")
            )
            if close_orders is None:
                self._reconciliation_blocked_symbols.add(symbol)
                if fail_closed:
                    raise RuntimeError(f"could not read close-order ledger for {symbol}")
                logger.error("❌ Close-order ledger unavailable; skipping trading cycle for %s", symbol)
                return False
            latest_close = close_orders[0] if close_orders else None
            if latest_close:
                close_status = str(latest_close.get("status") or "unknown").lower().replace("-", "_")
                raw_payload = latest_close.get("raw_payload") or {}
                known_tp1_partial = (
                    bool(trade.get("tp1_executed"))
                    and str(raw_payload.get("reason") or "").lower() == "tp1"
                )
                unresolved_order = close_status in {
                    "submitted", "partially_filled", "unknown", "needs_reconciliation"
                } and not known_tp1_partial
                if unresolved_order:
                    saved = self.state_manager.mark_trade_needs_reconciliation(
                        trade,
                        "reduce-only close order is not conclusively settled at Binance",
                    )
                    self._reconciliation_blocked_symbols.add(symbol)
                    if not saved:
                        unresolved_persistence.add(symbol)

        local_symbols = set(local_open) | self._reconciliation_blocked_symbols
        orphans = exchange_symbols - local_symbols
        if orphans:
            unresolved: set[str] = set()
            occupied_slots = {
                str(slot.get("symbol")): slot
                for slot in self.state_manager.get_occupied_position_slots()
                if slot.get("symbol")
            }
            active_trade_ids = {
                str(trade.get("id"))
                for trade in local
                if trade.get("status") in {"OPEN", "NEEDS_RECONCILIATION"}
                and trade.get("id")
            }
            for position in result.data:
                symbol = str(position.get("symbol") or "")
                if symbol not in orphans:
                    continue
                if not self._persist_orphan_position(
                    position,
                    occupied_slots.get(symbol),
                    active_trade_ids=active_trade_ids,
                ):
                    unresolved.add(symbol)
            self._reconciliation_blocked_symbols.update(orphans)
            unresolved_persistence.update(unresolved)
            logger.critical(
                "🛑 Persisted exchange-only positions for automatic reconciliation: %s",
                ", ".join(sorted(orphans - unresolved)),
            )

        if unresolved_persistence:
            message = "could not persist reconciliation state: " + ", ".join(sorted(unresolved_persistence))
            if fail_closed:
                raise RuntimeError(message)
            logger.error("❌ %s; skipping trading cycle", message)
            return False

        await self._auto_close_reconciliation_positions()
        try:
            refreshed = self.state_manager.get_open_trades_from_db()
        except Exception as exc:
            if fail_closed:
                raise RuntimeError("cannot refresh reconciliation state after automatic resolution") from exc
            logger.error("❌ Cannot refresh reconciliation state; skipping trading cycle: %s", exc)
            return False
        self._reconciliation_blocked_symbols = {
            str(trade.get("symbol")) for trade in refreshed
            if trade.get("status") == "NEEDS_RECONCILIATION" and trade.get("symbol")
        }
        await self._notify_reconciliation_required()
        return True

    def _release_stale_position_slots(
        self,
        *,
        local_trades: list[dict[str, Any]],
        exchange_symbols: set[str],
    ) -> None:
        """Release only provably stale slot metadata before trading.

        A previous run can terminate after a trade is closed/persisted but before
        its global position slot is released.  Such a slot must not block every
        later Testnet run.  This cleanup is deliberately fail-closed: a slot is
        released only when its symbol has neither an OPEN/NEEDS_RECONCILIATION
        local trade nor an exchange position.  Any slot associated with a live
        exchange symbol remains occupied for the normal reconciliation path.
        """
        active_trades = [
            trade
            for trade in local_trades
            if trade.get("status") in {"OPEN", "NEEDS_RECONCILIATION"}
        ]
        active_symbols = {
            str(trade.get("symbol"))
            for trade in active_trades
            if trade.get("symbol")
        }
        active_trade_ids = {
            str(identifier)
            for trade in active_trades
            for identifier in (trade.get("id"), trade.get("entry_order_id"), trade.get("trade_id"))
            if identifier is not None
        }

        for slot in self.state_manager.get_occupied_position_slots():
            symbol = str(slot.get("symbol") or "")
            trade_id = slot.get("trade_id")
            if not symbol or symbol in exchange_symbols or symbol in active_symbols:
                continue
            if trade_id is not None and str(trade_id) in active_trade_ids:
                continue
            released = self.state_manager.release_position_slot(
                symbol=symbol,
                trade_id=str(trade_id) if trade_id is not None else None,
                reservation_id=slot.get("reservation_id"),
            )
            if released:
                logger.warning(
                    "🧹 Released stale position slot {} for {} (trade_id={})",
                    slot.get("slot_no"),
                    symbol,
                    trade_id,
                )

    @staticmethod
    def _exchange_position_quantity(position: dict[str, Any]) -> float:
        info = position.get("info") or {}
        raw = position.get("contracts") or position.get("positionAmt") or info.get("positionAmt") or 0
        try:
            quantity = abs(float(raw))
        except (TypeError, ValueError):
            return 0.0
        return quantity if math.isfinite(quantity) else 0.0

    @staticmethod
    def _exchange_position_direction(position: dict[str, Any]) -> str:
        info = position.get("info") or {}
        side = str(
            position.get("side") or position.get("positionSide")
            or info.get("positionSide") or ""
        ).strip().upper()
        if side in {"LONG", "SHORT"}:
            return side
        raw = position.get("positionAmt") or info.get("positionAmt") or 0
        try:
            signed_quantity = float(raw)
        except (TypeError, ValueError):
            return ""
        return "LONG" if signed_quantity > 0 else "SHORT" if signed_quantity < 0 else ""

    async def _auto_close_reconciliation_positions(self) -> None:
        """Automatically resolve Testnet mismatches with persisted, reduce-only attempts."""
        if not bool(getattr(self.config, "auto_reconcile_close_enabled", False)):
            return
        environment = str(getattr(self.config, "environment", "testnet")).strip().lower()
        if environment != "testnet" or getattr(self.exchange, "is_testnet", False) is not True:
            logger.critical("🛑 Automatic reconciliation close is Testnet-only; no close was sent")
            return

        positions_result = await self.exchange.get_all_open_positions_result()
        if not positions_result.ok:
            logger.error("❌ Cannot auto-reconcile: exchange position query failed: %s", positions_result.error)
            return
        exchange_positions = {
            str(position.get("symbol")): position
            for position in positions_result.data
            if position.get("symbol") and self._exchange_position_quantity(position) > 0
        }
        records = [
            trade for trade in self.state_manager.get_open_trades_from_db()
            if trade.get("status") == "NEEDS_RECONCILIATION" and trade.get("symbol")
        ]

        async def persist_confirmed_fill(
            trade: dict[str, Any], ledger_order_id: int, exchange_order_id: str, fill: Any,
        ) -> bool:
            if not fill or not fill.is_pnl_eligible:
                return False
            direction = str(trade.get("direction") or "LONG").upper()
            return self.state_manager.record_trade_fill({
                "order_id": ledger_order_id,
                "trade_id": str(trade.get("id") or ""),
                "exchange": self.config.exchange.primary_exchange(),
                "symbol": str(trade.get("symbol") or ""),
                "exchange_order_id": exchange_order_id,
                "exchange_fill_id": fill.trade_ids[0] if fill.trade_ids else None,
                "side": "sell" if direction in {"LONG", "BUY"} else "buy",
                "quantity": fill.quantity,
                "price": fill.price,
                "fee_amount": fill.fee,
                "fee_currency": fill.fee_currency or None,
                "filled_at": fill.filled_at,
                "price_source": fill.price_source.value,
                "quantity_source": fill.quantity_source.value,
                "fee_source": fill.fee_source.value,
                "raw_payload": fill.as_record(),
            })

        def release_slot(trade: dict[str, Any]) -> None:
            self.state_manager.release_position_slot(
                trade_id=str(trade.get("entry_order_id") or trade.get("id") or "")
            )

        for trade in records:
            symbol = str(trade["symbol"])
            trade_id = str(trade.get("id") or trade.get("entry_order_id") or "")
            try:
                position = exchange_positions.get(symbol)
                if position is None:
                    if self.state_manager.mark_reconciliation_flat(
                        trade,
                        "Binance confirms zero exposure; no unverified exit price or PnL was recorded",
                    ):
                        release_slot(trade)
                        await self.exchange.cancel_protection_orders(symbol)
                        logger.warning("✅ Auto-resolved flat reconciliation record: %s", symbol)
                    continue

                if not bool(getattr(self.config, "trading_execution_enabled", False)):
                    logger.warning("⏸️ Reconciliation close is enabled but exchange execution is disabled: %s", symbol)
                    continue

                live_direction = self._exchange_position_direction(position)
                local_direction = str(trade.get("direction") or "").strip().upper()
                local_direction = {"BUY": "LONG", "SELL": "SHORT"}.get(local_direction, local_direction)
                if not live_direction or local_direction not in {"LONG", "SHORT"}:
                    self.state_manager.save_trade_state({
                        **trade,
                        "reconciliation_note": "position direction missing or unknown; automatic close withheld",
                    })
                    logger.critical("🛑 Position direction is incomplete; withholding automatic close for %s", symbol)
                    continue
                if live_direction != local_direction:
                    self.state_manager.save_trade_state({
                        **trade,
                        "reconciliation_note": (
                            f"position direction mismatch (local={local_direction}, exchange={live_direction}); "
                            "automatic close withheld"
                        ),
                    })
                    logger.critical("🛑 Direction mismatch; withholding automatic close for %s", symbol)
                    continue

                orders = self.state_manager.get_reconciliation_close_orders(trade_id)
                if orders is None:
                    logger.error("❌ Cannot read close-order ledger; withholding automatic close for %s", symbol)
                    continue
                latest_order = orders[0] if orders else None
                if latest_order:
                    status = str(latest_order.get("status") or "unknown").lower().replace("-", "_")
                    order_id = str(latest_order.get("exchange_order_id") or "")
                    client_order_id = str(latest_order.get("client_order_id") or "")
                    if status in {"submitted", "partially_filled", "unknown", "needs_reconciliation"}:
                        if order_id or client_order_id:
                            exchange_order = await self.exchange.fetch_order_for_reconciliation(
                                symbol,
                                order_id=order_id or None,
                                client_order_id=client_order_id or None,
                            )
                            if exchange_order is None:
                                self.state_manager.update_trade_order(
                                    int(latest_order["id"]),
                                    {"status": "canceled", "raw_payload": {"reason": "Binance confirms order absent"}},
                                )
                            else:
                                order_id = str(exchange_order.get("id") or exchange_order.get("orderId") or order_id)
                                status = str(exchange_order.get("status") or "unknown").lower().replace("-", "_")
                                self.state_manager.update_trade_order(
                                    int(latest_order["id"]),
                                    {
                                        "status": status,
                                        "exchange_order_id": order_id or None,
                                        "raw_payload": exchange_order,
                                    },
                                )
                                if status in {"open", "new", "pending", "submitted", "partially_filled", "unknown"}:
                                    self.state_manager.save_trade_state({
                                        **trade,
                                        "closing_order_id": order_id or None,
                                        "reconciliation_note": "reduce-only close intent is still pending at Binance",
                                    })
                                    continue
                                if status in {"closed", "filled"} and order_id:
                                    prior_fill = await self.exchange.fetch_fill_details(order_id, symbol)
                                    await persist_confirmed_fill(
                                        trade, int(latest_order["id"]), order_id, prior_fill
                                    )
                        else:
                            # Compatibility for historical unknown order rows that predate client IDs.
                            if await self.exchange.has_open_reduce_only_market_order(symbol):
                                continue
                            submitted_at = latest_order.get("submitted_at")
                            if submitted_at:
                                try:
                                    submitted = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
                                    if (datetime.now(timezone.utc) - submitted).total_seconds() < 60:
                                        continue
                                except (TypeError, ValueError):
                                    continue
                    elif status in {"open", "new", "pending", "partially_filled"}:
                        continue
                    if status in {"closed", "filled", "canceled", "expired"} and order_id:
                        prior_fill = await self.exchange.fetch_fill_details(order_id, symbol)
                        if prior_fill and prior_fill.is_pnl_eligible:
                            await persist_confirmed_fill(
                                trade, int(latest_order["id"]), order_id, prior_fill
                            )

                # The first snapshot may have changed while the prior order
                # was being looked up. Never submit from stale exposure data.
                fresh_positions = await self.exchange.get_all_open_positions_result()
                if not fresh_positions.ok:
                    logger.error("❌ Live position recheck failed; no close submitted for %s", symbol)
                    continue
                position = next(
                    (
                        candidate for candidate in fresh_positions.data
                        if str(candidate.get("symbol") or "") == symbol
                        and self._exchange_position_quantity(candidate) > 0
                    ),
                    None,
                )
                if position is None:
                    if self.state_manager.mark_reconciliation_flat(
                        trade,
                        "Binance confirms zero exposure before retry; no unverified PnL was recorded",
                    ):
                        release_slot(trade)
                        await self.exchange.cancel_protection_orders(symbol)
                    continue
                live_direction = self._exchange_position_direction(position)
                if not live_direction or (local_direction and live_direction != local_direction):
                    logger.critical("🛑 Live direction changed or became unknown; withholding close for %s", symbol)
                    continue
                quantity = self._exchange_position_quantity(position)
                if quantity <= 0:
                    continue
                intent_key = hashlib.sha256(f"{trade_id}:{symbol}".encode("utf-8")).hexdigest()[:12]
                client_order_id = f"apex-r-{intent_key}-{uuid.uuid4().hex[:8]}"[:36]
                exit_side = "sell" if live_direction == "LONG" else "buy"
                ledger_order_id = self.state_manager.record_trade_order({
                    "trade_id": trade_id,
                    "exchange": self.config.exchange.primary_exchange(),
                    "symbol": symbol,
                    "side": exit_side,
                    "order_type": "market",
                    "status": "submitted",
                    "client_order_id": client_order_id,
                    "requested_quantity": quantity,
                    "reduce_only": True,
                    "raw_payload": {"reason": "auto_reconciliation_reduce_only", "intent_persisted_before_submit": True},
                })
                if ledger_order_id is None:
                    logger.critical("🛑 Could not persist close intent; no order sent for %s", symbol)
                    continue

                try:
                    order = await self.exchange.reduce_only_close(
                        symbol=symbol,
                        amount=quantity,
                        reason="auto_reconciliation_reduce_only",
                        client_order_id=client_order_id,
                    )
                except Exception as exc:
                    self.state_manager.update_trade_order(
                        ledger_order_id,
                        {"status": "unknown", "raw_payload": {"error": str(exc)[:500]}},
                    )
                    self.state_manager.save_trade_state({
                        **trade,
                        "reconciliation_note": "reduce-only order outcome is uncertain; checking the persisted client ID on the next cycle",
                    })
                    logger.error("❌ Auto reconciliation order outcome uncertain for %s: %s", symbol, exc)
                    continue

                order_id = str(order.get("id") or order.get("orderId") or "")
                order_status = str(order.get("status") or "submitted").lower().replace("-", "_")
                if not order_id:
                    try:
                        found = await self.exchange.fetch_order_for_reconciliation(
                            symbol, client_order_id=client_order_id
                        )
                        if found:
                            order_id = str(found.get("id") or found.get("orderId") or "")
                            order_status = str(found.get("status") or order_status).lower().replace("-", "_")
                            order = {**order, **found}
                    except Exception as exc:
                        logger.warning("Order lookup by client ID pending for %s: %s", symbol, exc)

                ledger_updated = self.state_manager.update_trade_order(
                    ledger_order_id,
                    {
                        "status": order_status,
                        "exchange_order_id": order_id or None,
                        "raw_payload": order,
                    },
                )
                self.state_manager.save_trade_state({
                    **trade,
                    "closing_order_id": order_id or None,
                    "reconciliation_note": (
                        "reduce-only order submitted; awaiting Binance position and fill confirmation"
                    ),
                })
                if not ledger_updated:
                    logger.critical("🛑 Exchange order sent but ledger update failed for %s", symbol)

                fill = await self.exchange.fetch_fill_details(order_id, symbol) if order_id else None
                fill_saved = await persist_confirmed_fill(
                    trade, ledger_order_id, order_id, fill
                ) if fill and fill.is_pnl_eligible else False
                latest_positions = await self.exchange.get_all_open_positions_result()
                if not latest_positions.ok:
                    logger.error("❌ Cannot confirm residual exposure after close for %s", symbol)
                    continue
                residual = next(
                    (
                        candidate for candidate in latest_positions.data
                        if str(candidate.get("symbol") or "") == symbol
                        and self._exchange_position_quantity(candidate) > 0
                    ),
                    None,
                )
                if residual is not None:
                    residual_quantity = self._exchange_position_quantity(residual)
                    self.state_manager.save_trade_state({
                        **trade,
                        "remaining_quantity": residual_quantity,
                        "closing_order_id": order_id or None,
                        "reconciliation_note": "reduce-only close completed or partially filled; residual exposure remains and will be rechecked automatically",
                    })
                    logger.warning("⏳ Residual Testnet exposure for %s: %s", symbol, residual_quantity)
                    continue

                closed = False
                if ledger_updated and fill_saved and fill and fill.is_pnl_eligible:
                    closed = self.state_manager.mark_reconciliation_closed(
                        trade,
                        order_id=order_id,
                        fill=fill,
                        close_reason="auto_reconciliation_reduce_only",
                    )
                if closed:
                    release_slot(trade)
                    await self.exchange.cancel_protection_orders(symbol)
                    await self.telegram.send_reconciliation_closed(
                        symbol=symbol,
                        order_id=order_id,
                        price=fill.price,
                        quantity=fill.quantity,
                        fee=fill.fee,
                    )
                    continue

                if self.state_manager.mark_reconciliation_flat(
                    trade,
                    "Binance confirms zero exposure after reduce-only reconciliation; accounting remains unconfirmed",
                ):
                    release_slot(trade)
                    await self.exchange.cancel_protection_orders(symbol)
                    logger.warning("✅ Auto-resolved flat exposure for %s without fabricated PnL", symbol)
            except Exception as exc:
                logger.error("❌ Auto reconciliation close failed for %s: %s", symbol, exc)

    async def _notify_reconciliation_required(self) -> None:
        """Notify once per persisted unresolved-state snapshot; never mutate positions."""
        records = [
            trade for trade in self.state_manager.get_open_trades_from_db()
            if trade.get("status") == "NEEDS_RECONCILIATION"
        ]
        if not records:
            return
        payload = [
            {
                "id": str(record.get("id") or ""),
                "symbol": str(record.get("symbol") or ""),
                "status": str(record.get("status") or ""),
                "strategy": str(record.get("strategy") or ""),
                "reconciliation_note": str(record.get("reconciliation_note") or ""),
            }
            for record in records
        ]
        alert_key = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if alert_key == self.state_manager.get_reconciliation_alert_key():
            return
        if await self.telegram.send_reconciliation_required(records):
            self.state_manager.mark_reconciliation_alerted(alert_key)

    def _persist_orphan_position(
        self,
        position: dict[str, Any],
        slot: dict[str, Any] | None,
        *,
        active_trade_ids: set[str] | None = None,
    ) -> bool:
        """Persist enough exchange facts to block an orphan safely without fake PnL."""
        symbol = str(position.get("symbol") or "")
        try:
            entry_price = float(
                position.get("entryPrice") or position.get("average") or 0.0
            )
            contracts = abs(float(
                position.get("contracts") or position.get("positionAmt") or 0.0
            ))
            leverage = max(1, int(float(position.get("leverage") or 1)))
        except (TypeError, ValueError):
            return False
        if not symbol or entry_price <= 0 or contracts <= 0:
            logger.error("❌ Cannot persist orphan %s without entry price and quantity", symbol)
            return False
        direction = "SHORT" if str(position.get("side") or "").lower() in {"short", "sell"} else "LONG"
        slot_trade_id = str((slot or {}).get("trade_id") or "")
        trade_id = (
            slot_trade_id
            if slot_trade_id and (active_trade_ids is None or slot_trade_id in active_trade_ids)
            else f"orphan-{symbol}-{int(time.time() * 1000)}"
        )
        record = {
            "id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "mode": str(self.config.active_mode),
            "strategy": "RECONCILIATION",
            "exchange": self.config.exchange.primary_exchange(),
            "entry_price": entry_price,
            "entry_order_id": trade_id,
            "entry_price_source": "unconfirmed",
            "entry_quantity_source": "unconfirmed",
            "entry_fee_source": "unconfirmed",
            "pnl_source": "unconfirmed",
            "size_usd": (entry_price * contracts) / leverage,
            "margin_usd": (entry_price * contracts) / leverage,
            "notional_usd": entry_price * contracts,
            "entry_quantity": contracts,
            "remaining_quantity": contracts,
            "leverage": leverage,
            "status": "NEEDS_RECONCILIATION",
            "reconciliation_note": "orphan exchange position recovered during startup reconciliation",
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        return bool(self.state_manager.save_trade_state(record))

    async def _roll_risk_day_if_needed(self, target_day: str | None = None) -> bool:
        """Refresh the daily risk projection at UTC day rollover; fail closed."""
        target_day = target_day or datetime.now(timezone.utc).date().isoformat()
        if target_day == self._risk_day:
            return False

        metrics = self.state_manager.get_daily_confirmed_metrics()
        if metrics is None:
            raise RuntimeError(
                "confirmed daily risk metrics unavailable; refusing to roll risk day"
            )

        previous = (
            self._risk_day,
            self._daily_loss_used,
            self._daily_realized_pnl,
        )
        self._risk_day = target_day
        self._daily_loss_used = float(metrics.get("loss_used") or 0.0)
        self._daily_realized_pnl = float(metrics.get("realized_pnl") or 0.0)
        persisted = await self.state_manager.update_bot_status(
            balance=self._current_balance if self._current_balance > 0 else None,
            daily_loss_used=self._daily_loss_used,
            daily_realized_pnl=self._daily_realized_pnl,
            daily_loss_limit=self._daily_loss_limit if self._daily_loss_limit > 0 else None,
            risk_day=target_day,
        )
        if not persisted:
            (
                self._risk_day,
                self._daily_loss_used,
                self._daily_realized_pnl,
            ) = previous
            raise RuntimeError(
                "could not persist daily risk rollover; refusing to continue trading"
            )

        logger.info(
            "Daily risk state rolled to {} from confirmed trades: loss_used={}, pnl={}",
            target_day,
            self._daily_loss_used,
            self._daily_realized_pnl,
        )
        return True

    async def process_market_cycle(self) -> None:
        logger.info(f"Market cycle: {datetime.now(timezone.utc).isoformat()}")
        await self._roll_risk_day_if_needed()
        try:
            reconciled = await self._reconcile_before_trading(fail_closed=False)
        except Exception as exc:
            logger.error("❌ Periodic reconciliation failed; skipping trading cycle: %s", exc)
            return
        if not reconciled:
            return

        if self.config.trading.auto_symbol_scan:
            now = time.time()
            if now - self._last_symbol_scan_at >= self.config.trading.symbol_scan_interval_seconds:
                scanned = await self.exchange.get_top_usdt_perpetual_symbols(
                    limit=self.config.trading.symbol_scan_limit,
                    min_quote_volume_usdt=self.config.trading.min_quote_volume_usdt,
                    base_symbols=self.config.trading.symbols,
                )
                if scanned:
                    self.config.trading.symbols = scanned
                    logger.info("🔎 رموز المسح الحجمي الحالية: %s", ", ".join(scanned))
                self._last_symbol_scan_at = now

        cycle_errors: list[str] = []
        await self.universe_manager.refresh_if_due()
        all_open_positions = self.state_manager.get_open_trades_from_db()
        open_symbols = [
            str(position.get("symbol")) for position in all_open_positions
            if position.get("symbol")
        ]
        cycle_symbols = self.universe_manager.get_symbols_for_cycle(open_symbols)
        entries_started = 0
        for symbol in cycle_symbols:
            slot_reservation_id: str | None = None
            order_submitted = False
            try:
                # 1. جلب البيانات
                if symbol in self._reconciliation_blocked_symbols:
                    logger.critical("🛑 %s محجوب حتى اكتمال المصالحة الآلية والتحقق من Binance", symbol)
                    continue
                candles = await self.market_data.get_ohlcv(
                    symbol, self.config.trading.timeframe, limit=300
                )
                if candles is None or candles.empty:
                    continue

                ticker = await self.exchange.get_ticker(symbol)
                current_price = float(ticker.get("last") or 0.0)
                if current_price <= 0:
                    logger.warning("Skipping %s: exchange returned no valid ticker", symbol)
                    continue

                # 2. إدارة المراكز المفتوحة
                open_positions = all_open_positions
                symbol_positions = [
                    p for p in open_positions
                    if p.get("symbol") == symbol and p.get("status") == "OPEN"
                ]

                for pos in symbol_positions:
                    pos_obj = self.state_manager.reconstruct_position(pos)
                    if pos_obj is None:
                        continue

                    # ✅ إصلاح خلل حرج (مؤكَّد): pos_obj لم يكن يُسجَّل أبداً في
                    # PositionManager._positions، لذا كانت update_price() ترجع
                    # None دائماً لأي مركز مُستعاد من قاعدة البيانات — أي أن
                    # وقف الخسارة/جني الأرباح الجزئي/Trailing Stop المُدار
                    # داخلياً لم يكن يعمل إطلاقاً لأي صفقة قائمة بالفعل.
                    if self.position_manager.get_position(pos_obj.id) is None:
                        self.position_manager.add_position(pos_obj)

                    action = self.position_manager.update_price(
                        pos_obj.id, current_price
                    )

                    if action and action.get("action") == "partial_close":
                        # ✅ إصلاح: partial_close لم تكن تُعالَج إطلاقاً من قبل —
                        # كانت تُطلق من PositionManager وتُهمَل بصمت في main.py.
                        pct = action.get("percentage", 50)
                        logger.info(
                            f"🎯 TP1 وصل لـ {symbol} — إغلاق جزئي مطلوب ({pct}%)"
                        )
                        try:
                            available_quantity = (
                                pos_obj.remaining_quantity
                                or (pos_obj.size_usd * pos_obj.leverage / pos_obj.entry_price)
                            )
                            partial_amount = available_quantity * (pct / 100.0)
                            partial_order = await self.exchange.reduce_only_close(
                                symbol=symbol,
                                amount=partial_amount,
                                reason="tp1",
                            )
                            partial_order_id = str(partial_order.get("id") or "")
                            partial_ledger_id = self.state_manager.record_trade_order({
                                "trade_id": pos_obj.id,
                                "exchange": self.config.exchange.primary_exchange(),
                                "symbol": symbol,
                                "side": "sell" if pos_obj.direction.value == "LONG" else "buy",
                                "order_type": str(partial_order.get("type") or "MARKET").lower(),
                                "status": str(partial_order.get("status") or "submitted").lower(),
                                "exchange_order_id": partial_order_id or None,
                                "client_order_id": partial_order.get("clientOrderId"),
                                "requested_quantity": partial_amount,
                                "reduce_only": True,
                                "raw_payload": {"reason": "tp1"},
                            })
                            self.state_manager.record_trading_event(
                                "ORDER_SUBMITTED",
                                f"order_submitted:{self.config.exchange.primary_exchange()}:{partial_order_id or partial_order.get('clientOrderId')}",
                                exchange=self.config.exchange.primary_exchange(),
                                trade_id=pos_obj.id,
                                order_id=partial_ledger_id,
                                symbol=symbol,
                                payload={"reason": "tp1", "requested_quantity": partial_amount},
                            )
                            partial_fill = (
                                await self.exchange.fetch_fill_details(partial_order_id, symbol)
                                if partial_order_id else None
                            )
                            if (
                                partial_fill is None
                                or not partial_fill.is_pnl_eligible
                                or pos.get("entry_fee_source") != "exchange_fill"
                            ):
                                self.state_manager.mark_trade_needs_reconciliation(
                                    pos,
                                    "partial close fill could not be confirmed from exchange",
                                )
                                self._reconciliation_blocked_symbols.add(symbol)
                                raise RuntimeError("partial close requires reconciliation")

                            self.state_manager.record_trade_fill({
                                "order_id": partial_ledger_id,
                                "trade_id": pos_obj.id,
                                "exchange": self.config.exchange.primary_exchange(),
                                "symbol": symbol,
                                "exchange_order_id": partial_order_id or None,
                                "side": "sell" if pos_obj.direction.value == "LONG" else "buy",
                                "quantity": partial_fill.quantity,
                                "price": partial_fill.price,
                                "fee_amount": partial_fill.fee,
                                "price_source": partial_fill.price_source.value,
                                "quantity_source": partial_fill.quantity_source.value,
                                "fee_source": partial_fill.fee_source.value,
                                "fee_currency": partial_fill.fee_currency,
                                "raw_payload": partial_fill.as_record(),
                            })
                            self.state_manager.record_trading_event(
                                "TP1_EXECUTED",
                                f"tp1_executed:{pos_obj.id}:{partial_order_id}:{partial_fill.price}:{partial_fill.quantity}",
                                exchange=self.config.exchange.primary_exchange(),
                                trade_id=pos_obj.id,
                                order_id=partial_ledger_id,
                                symbol=symbol,
                                payload=partial_fill.as_record(),
                            )
                            partial_pnl = (
                                (partial_fill.price - pos_obj.entry_price)
                                * partial_fill.quantity
                                if pos_obj.direction.value == "LONG"
                                else (pos_obj.entry_price - partial_fill.price)
                                * partial_fill.quantity
                            ) - partial_fill.fee
                            if not self.state_manager.record_partial_close({
                                "trade_id": pos_obj.id,
                                "reason": "tp1",
                                "price": partial_fill.price,
                                "amount_closed": partial_fill.quantity,
                                "pnl": partial_pnl,
                                "fee": partial_fill.fee,
                                "price_source": partial_fill.price_source.value,
                                "quantity_source": partial_fill.quantity_source.value,
                                "fee_source": partial_fill.fee_source.value,
                                "fee_currency": partial_fill.fee_currency,
                                "pnl_source": "exchange_fill",
                                "exchange_order_id": partial_order_id,
                            }):
                                raise RuntimeError("partial close executed but persistence failed")
                            # Keep the parent trade quantity aligned with the
                            # confirmed exchange fill; never infer it from a
                            # candle or requested amount.
                            self.state_manager.save_trade_state({
                                **pos,
                                "remaining_quantity": max(
                                    0.0,
                                    float(pos.get("remaining_quantity") or pos_obj.entry_quantity)
                                    - float(partial_fill.quantity),
                                ),
                                "tp1_executed": True,
                            })
                        except Exception as partial_err:
                            logger.error(f"❌ فشل تنفيذ الإغلاق الجزئي (TP1) لـ {symbol}: {partial_err}")
                        else:
                            pos_obj.apply_partial_close(partial_fill.quantity)
                            if not self.state_manager.save_trade_state({
                                **pos,
                                "tp1_executed": True,
                                "remaining_quantity": pos_obj.remaining_quantity,
                                "entry_quantity": pos_obj.entry_quantity,
                            }):
                                raise RuntimeError("partial close executed but state persistence failed")
                            await self.telegram.send_partial_close(
                                pos_obj, partial_fill.price, pct, partial_pnl=partial_pnl,
                            )

                    elif action and action.get("action") == "close":
                        order = await self.exchange.close_position(
                            symbol=symbol,
                            position_id=pos_obj.id,
                            reason=action.get("reason", "unknown"),
                            price=current_price
                        )

                        close_order_id = str(order.get("id") or "")
                        close_ledger_id = self.state_manager.record_trade_order({
                            "trade_id": pos_obj.id,
                            "exchange": self.config.exchange.primary_exchange(),
                            "symbol": symbol,
                            "side": "sell" if pos_obj.direction.value == "LONG" else "buy",
                            "order_type": str(order.get("type") or "MARKET").lower(),
                            "status": str(order.get("status") or "submitted").lower(),
                            "exchange_order_id": close_order_id or None,
                            "client_order_id": order.get("clientOrderId"),
                            "requested_quantity": pos_obj.remaining_quantity,
                            "reduce_only": True,
                            "raw_payload": {"reason": action.get("reason", "unknown")},
                        })
                        self.state_manager.record_trading_event(
                            "ORDER_SUBMITTED",
                            f"order_submitted:{self.config.exchange.primary_exchange()}:{close_order_id or order.get('clientOrderId')}",
                            exchange=self.config.exchange.primary_exchange(),
                            trade_id=pos_obj.id,
                            order_id=close_ledger_id,
                            symbol=symbol,
                            payload={"reason": action.get("reason", "unknown")},
                        )
                        fill = (
                            await self.exchange.fetch_fill_details(
                                close_order_id, symbol, reference_price=current_price
                            )
                            if close_order_id else None
                        )
                        if (
                            fill is None
                            or not fill.is_pnl_eligible
                            or pos.get("entry_fee_source") != "exchange_fill"
                        ):
                            logger.critical(
                                "🛑 إغلاق {} بلا Fill مؤكد؛ لن يُحتسب PnL وسيحتاج إلى مصالحة.",
                                symbol,
                            )
                            self._reconciliation_blocked_symbols.add(symbol)
                            self.state_manager.save_trade_state({
                                **pos,
                                "status": "NEEDS_RECONCILIATION",
                                "closing_order_id": close_order_id or None,
                                "exit_price_source": "unconfirmed",
                                "exit_quantity_source": "unconfirmed",
                                "exit_fee_source": "unconfirmed",
                                "pnl_source": "unconfirmed",
                                "reconciliation_note": "close fill could not be confirmed from exchange",
                                "closed_at": datetime.now(timezone.utc).isoformat(),
                            })
                            continue

                        self.state_manager.record_trade_fill({
                            "order_id": close_ledger_id,
                            "trade_id": pos_obj.id,
                            "exchange": self.config.exchange.primary_exchange(),
                            "symbol": symbol,
                            "exchange_order_id": close_order_id or None,
                            "side": "sell" if pos_obj.direction.value == "LONG" else "buy",
                            "quantity": fill.quantity,
                            "price": fill.price,
                            "fee_amount": fill.fee,
                            "fee_currency": fill.fee_currency or None,
                            "exchange_fill_id": fill.trade_ids[0] if fill.trade_ids else None,
                            "filled_at": fill.filled_at,
                            "reference_price": fill.reference_price,
                            "slippage_bps": fill.slippage_bps,
                            "mark_price": fill.mark_price,
                            "trigger_price": fill.trigger_price,
                            "realized_pnl": None,
                            "price_source": fill.price_source.value,
                            "quantity_source": fill.quantity_source.value,
                            "fee_source": fill.fee_source.value,
                            "fee_currency": fill.fee_currency,
                            "raw_payload": fill.as_record(),
                        })
                        self.state_manager.record_trading_event(
                            "ORDER_FILLED",
                            f"order_filled:{self.config.exchange.primary_exchange()}:{close_order_id}:{fill.price}:{fill.quantity}",
                            exchange=self.config.exchange.primary_exchange(),
                            trade_id=pos_obj.id,
                            order_id=close_ledger_id,
                            symbol=symbol,
                            payload=fill.as_record(),
                        )

                        # ✅ إصلاح خلل حرج (مؤكَّد): close_position() في
                        # PositionManager (الذي يحسب pnl الفعلي) لم يكن يُستدعى
                        # أبداً — النتيجة: pnl محفوظ دائماً = 0 في القاعدة
                        # وفي إشعار Telegram، و_daily_realized_pnl/_daily_loss_used
                        # لا يتحدّثان أبداً، ما يجعل "حد الخسارة اليومي" مجرد رقم
                        # عرض بلا أي تفعيل فعلي.
                        pos_obj.exit_fee = fill.fee
                        closed_pos = self.position_manager.close_position(
                            pos_obj.id, fill.price, action.get("reason", "manual")
                        )
                        realized_pnl = closed_pos.pnl if closed_pos else 0.0

                        self._daily_realized_pnl += realized_pnl
                        if realized_pnl < 0:
                            self._daily_loss_used += abs(realized_pnl)

                        self.state_manager.save_trade_state({
                            **pos,
                            "status": "CLOSED",
                            "exit_price": fill.price,
                            "closing_order_id": close_order_id,
                            "exit_price_source": fill.price_source.value,
                            "exit_quantity_source": fill.quantity_source.value,
                            "exit_fee_source": fill.fee_source.value,
                            "pnl_source": "exchange_fill",
                            "exit_fee": fill.fee,
                            "exit_fee_currency": fill.fee_currency or None,
                            "exit_filled_at": fill.filled_at,
                            "exit_slippage_bps": fill.slippage_bps,
                            "exit_mark_price": fill.mark_price,
                            "exit_trigger_price": fill.trigger_price,
                            "close_reason": action.get("reason"),
                            "pnl": realized_pnl,
                            "pnl_pct": closed_pos.pnl_pct if closed_pos else 0.0,
                            "pnl_account_pct": (
                                round(
                                    (realized_pnl / account_balance) * 100,
                                    4,
                                )
                                if (account_balance := float(
                                    pos.get("account_balance_at_entry") or self._current_balance
                                )) > 0
                                else None
                            ),
                            # ✅ إصلاح: عمود "duration_minutes" مطلوب من App.jsx
                            # ولم يكن يُحفَظ أبداً — Position.duration_minutes
                            # موجودة كخاصية محسوبة لكنها لم تُصدَّر لقاعدة البيانات.
                            "duration_minutes": round(closed_pos.duration_minutes, 2) if closed_pos else None,
                            "closed_at": datetime.now(timezone.utc).isoformat()
                        })
                        if closed_pos:
                            closed_pos.pnl = realized_pnl
                        await self.telegram.send_trade_closed(
                            closed_pos or pos_obj, action.get("reason", "")
                        )
                        self.state_manager.record_trading_event(
                            "TRADE_CLOSED",
                            f"trade_closed:{pos_obj.id}:{close_order_id}:{fill.price}:{realized_pnl}",
                            exchange=self.config.exchange.primary_exchange(),
                            trade_id=pos_obj.id,
                            order_id=close_ledger_id,
                            symbol=symbol,
                            payload={
                                "reason": action.get("reason", ""),
                                "realized_pnl": realized_pnl,
                            },
                        )
                        self.state_manager.record_learning_event({
                            "event_type": "trade_outcome",
                            "trade_id": str(pos_obj.id),
                            "symbol": symbol,
                            "strategy": pos.get("strategy"),
                            "strategy_subtype": pos.get("strategy_subtype"),
                            "outcome": (
                                "win" if realized_pnl > 0
                                else "loss" if realized_pnl < 0
                                else "flat"
                            ),
                            "realized_pnl": realized_pnl,
                            "fee_amount": fill.fee,
                            "slippage_bps": fill.slippage_bps,
                            "features": {
                                "close_reason": action.get("reason", ""),
                                "pnl_source": "exchange_fill",
                                "entry_price_source": pos.get("entry_price_source"),
                                "exit_price_source": fill.price_source.value,
                                "exit_quantity_source": fill.quantity_source.value,
                                "exit_fee_source": fill.fee_source.value,
                            },
                        })
                        self.state_manager.release_position_slot(
                            trade_id=str(pos.get("entry_order_id") or pos_obj.id)
                        )

                if symbol in self._reconciliation_blocked_symbols:
                    logger.critical("🛑 %s remains blocked until exchange reconciliation completes", symbol)
                    continue

                # ✅ إصلاح خلل حرج (مؤكَّد): تفعيل فعلي لحد الخسارة اليومي —
                # لم يكن موجوداً في أي مكان بالكود سابقاً رغم حساب الحد.
                if self._daily_loss_used >= getattr(self, "_daily_loss_limit", float("inf")):
                    logger.warning(
                        f"🛑 تم بلوغ حد الخسارة اليومي ({self._daily_loss_used:.2f}$ / "
                        f"{self._daily_loss_limit:.2f}$) — إيقاف فتح صفقات جديدة لبقية اليوم على {symbol}"
                    )
                    continue

                # Evaluate the closed-candle signal once. Shadow Mode is
                # observational and runs before the entry gate so read-only
                # reconciliation runners can still collect signal evidence.
                signal_result = self.signal_engine.evaluate_market(candles, symbol)
                # Shadow is evaluated on the same closed-candle frame as the
                # live signal, but is stored in an independent paper ledger.
                if self.config.shadow_mode:
                    closed_frame = candles.iloc[:-1].copy()
                    analyzed_shadow = self.signal_engine.indicator_calculator.calculate_all(
                        closed_frame
                    )
                    for open_shadow in self.state_manager.get_open_shadow_signals(symbol):
                        outcome = update_shadow_outcome(open_shadow, analyzed_shadow)
                        if outcome:
                            evaluated = int(open_shadow.get("evaluated_candles") or 0) + 1
                            horizon = int(open_shadow.get("horizon_candles") or 12)
                            if evaluated >= horizon and outcome.get("status") == "OPEN":
                                outcome["status"] = "TIMEOUT"
                                outcome["exit_reason"] = "horizon_reached"
                            outcome["evaluated_candles"] = evaluated
                            outcome["evaluated_at"] = datetime.now(timezone.utc).isoformat()
                            self.state_manager.update_shadow_signal(
                                open_shadow.get("idempotency_key", ""), outcome
                            )
                    observation = build_shadow_observation(
                        analyzed_shadow,
                        signal_result,
                        symbol,
                        self.config.trading.timeframe,
                        horizon_candles=int(os.getenv("SHADOW_HORIZON_CANDLES", "12")),
                    )
                    observation["features"]["committee"] = build_committee_assessment(observation)
                    self.state_manager.record_shadow_signal(observation)
                from bot.signals.signal_engine import TradeDirection
                action_val = signal_result.get("action")
                if action_val in (TradeDirection.HOLD, "HOLD"):
                    candle_key = str(candles.index[-1]) if len(candles.index) else "unknown"
                    indicators = signal_result.get("indicators") or {}
                    no_signal_key = f"signal:{symbol}:{candle_key}:HOLD"
                    self.state_manager.record_strategy_signal({
                        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, no_signal_key)),
                        "idempotency_key": no_signal_key,
                        "symbol": symbol,
                        "mode": str(self.config.active_mode),
                        "strategy": signal_result.get("strategy") or "ROUTER",
                        "strategy_subtype": signal_result.get("strategy_subtype") or "none",
                        "action": "HOLD",
                        "confidence": signal_result.get("confidence", 0.0),
                        "rule_score": signal_result.get("rule_score", 0.0),
                        "reason": signal_result.get("reason", "No valid signal detected"),
                        "entry_price": indicators.get("close") or current_price,
                        "atr_value": indicators.get("atr_value") or None,
                        "status": "no_signal",
                    })
                    logger.info(
                        "ℹ️ No entry signal for {}: reason={} rsi={} ema200={} atr={}",
                        symbol,
                        signal_result.get("reason", "No valid signal detected"),
                        indicators.get("rsi"),
                        indicators.get("ema_200"),
                        indicators.get("atr_value"),
                    )
                    continue
                strategy = signal_result.get("strategy") or "UNKNOWN"
                strategy_subtype = signal_result.get("strategy_subtype") or "unknown"
                if self.config.shadow_mode:
                    shadow = recommend_shadow_action(
                        signal_result,
                        min_confidence=float(self.config.risk.min_confidence),
                    )
                    candle_key = str(candles.index[-1]) if len(candles.index) else "unknown"
                    self.state_manager.record_learning_event({
                        "idempotency_key": (
                            f"shadow:{symbol}:{candle_key}:{strategy_subtype}:"
                            f"{shadow['candidate_action']}"
                        ),
                        "event_type": "shadow_signal",
                        "symbol": symbol,
                        "strategy": strategy,
                        "strategy_subtype": strategy_subtype,
                        "outcome": shadow["shadow_action"],
                        "model_version": shadow["model_version"],
                        "features": {
                            "candle_key": candle_key,
                            "candidate_action": shadow["candidate_action"],
                            "candidate_confidence": shadow["candidate_confidence"],
                            "shadow_action": shadow["shadow_action"],
                            "shadow_confidence": shadow["shadow_confidence"],
                            "decision": shadow["decision"],
                            "reason": shadow["reason"],
                            "execution_enabled": self.config.trading_execution_enabled,
                            "allow_new_entries": self.config.allow_new_entries,
                        },
                    })

                # Reconciliation-only runners keep execution enabled so they
                # can close/reduce existing positions, but must never turn a
                # candidate signal into a new entry.  Do this check before
                # risk sizing, slot reservation, and place_order: the exchange
                # gate is a final safety net, not normal control flow.
                if not self.config.allow_new_entries:
                    logger.info(
                        "Skipping new entry for {}: ALLOW_NEW_ENTRIES is false",
                        symbol,
                    )
                    continue

                # Persist attribution before any order attempt. This is a signal
                # audit record, not evidence of a fill or a trade.
                atr_value = float(signal_result.get("indicators", {}).get("atr_value") or 0.0)
                atr_multiplier = float(getattr(risk_cfg := self.config.risk, "atr_stop_multiplier", 2.0))
                candle_key = str(candles.index[-1]) if len(candles.index) else "unknown"
                signal_idempotency_key = (
                    f"signal:{symbol}:{candle_key}:{strategy_subtype}:{str(action_val).upper()}"
                )
                signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, signal_idempotency_key))
                self.state_manager.record_strategy_signal({
                    "id": signal_id,
                    "idempotency_key": signal_idempotency_key,
                    "symbol": symbol,
                    "mode": str(self.config.active_mode),
                    "strategy": strategy,
                    "strategy_subtype": strategy_subtype,
                    "action": str(action_val).upper(),
                    "confidence": signal_result.get("confidence", 0.0),
                    "rule_score": signal_result.get("rule_score", signal_result.get("confidence", 0.0)),
                    "reason": signal_result.get("reason", ""),
                    "entry_price": current_price,
                    "atr_value": atr_value or None,
                    "atr_multiplier": atr_multiplier,
                    "status": "candidate",
                })

                # ✅ إصلاح: تمرير المراكز المفتوحة لـ RiskManager
                if not self.risk_manager.check_risk_limits(
                    type("S", (), signal_result)(),
                    open_positions=symbol_positions
                ):
                    self.state_manager.update_strategy_signal_status(
                        signal_idempotency_key,
                        "rejected_risk_limits",
                        "RiskManager.check_risk_limits rejected the candidate",
                    )
                    continue

                # 4. حساب الأسعار وتنفيذ الأمر
                entry_price = current_price
                risk_cfg = self.config.risk
                # Prefer strategy-specific percentages when supplied by the
                # remote strategy contract; otherwise derive them from the
                # strategy price levels generated on the closed candle.
                reference_price = float(signal_result.get("indicators", {}).get("close") or entry_price)
                configured_sl = signal_result.get("stop_loss")
                configured_tp1 = signal_result.get("take_profit_1")
                configured_tp2 = signal_result.get("take_profit_2")
                sl_pct = float(signal_result.get("stop_loss_pct") or (abs(float(configured_sl) - reference_price) / reference_price if configured_sl else risk_cfg.default_sl_pct / 100))
                tp1_pct = float(signal_result.get("take_profit_pct") or (abs(float(configured_tp1) - reference_price) / reference_price if configured_tp1 else risk_cfg.tp1_pct / 100))
                tp2_pct = float(signal_result.get("take_profit_pct") or (abs(float(configured_tp2) - reference_price) / reference_price if configured_tp2 else risk_cfg.tp2_pct / 100))
                leverage = risk_cfg.max_leverage

                # Prefer a volatility-derived stop. Percentage SL remains a
                # compatibility fallback when ATR is unavailable during warm-up.
                stop_distance = (
                    atr_value * atr_multiplier
                    if atr_value > 0 and atr_multiplier > 0
                    else entry_price * sl_pct
                )

                if str(action_val).upper() in ("LONG", "BUY"):
                    stop_loss = round(entry_price - stop_distance, 6)
                    take_profit_1 = round(entry_price * (1 + tp1_pct), 6)
                    take_profit_2 = round(entry_price * (1 + tp2_pct), 6)
                    side = "buy"
                else:
                    stop_loss = round(entry_price + stop_distance, 6)
                    take_profit_1 = round(entry_price * (1 - tp1_pct), 6)
                    take_profit_2 = round(entry_price * (1 - tp2_pct), 6)
                    side = "sell"

                balance = await self.exchange.get_balance()
                if balance <= 0:
                    logger.error("Skipping new entry for %s: balance unavailable", symbol)
                    self.state_manager.update_strategy_signal_status(
                        signal_idempotency_key,
                        "rejected_balance",
                        "Exchange balance unavailable or non-positive",
                    )
                    continue
                self._current_balance = balance
                size_usd = self._calculate_position_size(
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    leverage=leverage,
                    account_balance=balance,
                )

                # ✅ تحقق evaluate_risk قبل التنفيذ
                if not self.risk_manager.evaluate_risk(
                    account_balance=balance,
                    size_usd=size_usd,
                    leverage=leverage,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    direction=side
                ):
                    self.state_manager.update_strategy_signal_status(
                        signal_idempotency_key,
                        "rejected_risk",
                        "RiskManager.evaluate_risk rejected the candidate",
                    )
                    continue

                if entries_started >= self.config.trading.max_new_entries_per_cycle:
                    logger.info(
                        "Skipping new entry for %s: per-cycle entry limit reached",
                        symbol,
                    )
                    self.state_manager.update_strategy_signal_status(
                        signal_idempotency_key,
                        "rejected_cycle_limit",
                        "Maximum new entries per cycle already reached",
                    )
                    continue

                slot_reservation_id = f"{self._slot_owner}-{uuid.uuid4().hex}"
                slot = self.state_manager.try_reserve_position_slot(
                    symbol,
                    self._slot_owner,
                    slot_reservation_id,
                    max_slots=self.config.trading.max_open_positions,
                )
                if not slot:
                    logger.info("Skipping %s: all global position slots are occupied", symbol)
                    self.state_manager.update_strategy_signal_status(
                        signal_idempotency_key,
                        "rejected_no_slot",
                        "All global position slots are occupied",
                    )
                    continue

                # size_usd is margin; the exchange order uses the leveraged notional.
                notional_usd = size_usd * leverage
                order_amount = notional_usd / entry_price

                # 5. تنفيذ الأمر على البورصة
                order = await self.exchange.place_order(
                    symbol=symbol,
                    side=side,
                    amount=order_amount,
                    price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit_1,
                    leverage=leverage,
                    client_order_id=f"apex-{symbol.replace('/', '')}-{int(time.time() * 1000)}",
                    take_profit_2=take_profit_2,
                    tp1_fraction=0.5,
                )
                order_submitted = True
                entries_started += 1

                entry_order_id = str(order.get("id") or "")
                order_ledger_id = self.state_manager.record_trade_order({
                    "exchange": self.config.exchange.primary_exchange(),
                    "symbol": symbol,
                    "side": side,
                    "order_type": str(order.get("type") or "MARKET").lower(),
                    "status": str(order.get("status") or "submitted").lower(),
                    "exchange_order_id": entry_order_id or None,
                    "client_order_id": order.get("clientOrderId"),
                    "requested_quantity": order_amount,
                    "requested_price": entry_price,
                    "reduce_only": False,
                    "raw_payload": {
                        "protection_order_ids": order.get("protection_order_ids", []),
                    },
                })
                self.state_manager.record_trading_event(
                    "ORDER_SUBMITTED",
                    f"order_submitted:{self.config.exchange.primary_exchange()}:{entry_order_id or order.get('clientOrderId')}",
                    exchange=self.config.exchange.primary_exchange(),
                    order_id=order_ledger_id,
                    symbol=symbol,
                    payload={"side": side, "requested_quantity": order_amount},
                )
                if entry_order_id:
                    self.state_manager.bind_position_slot(
                        slot_reservation_id, entry_order_id
                    )
                entry_fill = (
                    await self.exchange.fetch_fill_details(
                        entry_order_id, symbol, reference_price=entry_price
                    )
                    if entry_order_id else None
                )
                protection_ids = [str(value) for value in order.get("protection_order_ids", [])]
                if protection_ids:
                    self.state_manager.record_trading_event(
                        "PROTECTION_PLACED",
                        f"protection_placed:{entry_order_id}:{','.join(protection_ids)}",
                        exchange=self.config.exchange.primary_exchange(),
                        trade_id=entry_order_id or None,
                        order_id=order_ledger_id,
                        symbol=symbol,
                        payload={"protection_order_ids": protection_ids},
                    )

                if entry_fill is None or not entry_fill.is_pnl_eligible:
                    self._reconciliation_blocked_symbols.add(symbol)
                    self.state_manager.save_trade_state({
                        "id": entry_order_id,
                        "symbol": symbol,
                        "direction": str(action_val).upper(),
                        "status": "NEEDS_RECONCILIATION",
                        "entry_order_id": entry_order_id,
                        "signal_id": signal_id,
                        "strategy": strategy,
                        "strategy_subtype": strategy_subtype,
                        "entry_client_order_id": order.get("clientOrderId"),
                        "entry_price_source": entry_fill.price_source.value if entry_fill else "unconfirmed",
                        "entry_quantity_source": entry_fill.quantity_source.value if entry_fill else "unconfirmed",
                        "entry_fee_source": entry_fill.fee_source.value if entry_fill else "unconfirmed",
                        "pnl_source": "unconfirmed",
                        "reconciliation_note": "entry fill or fee could not be confirmed",
                    })
                    raise RuntimeError("entry fill is not eligible for accounting; reconciliation required")

                entry_price = entry_fill.price
                entry_quantity = entry_fill.quantity
                notional_usd = entry_price * entry_quantity
                size_usd = notional_usd / leverage
                self.state_manager.record_trade_fill({
                    "order_id": order_ledger_id,
                    "trade_id": entry_order_id or None,
                    "exchange": self.config.exchange.primary_exchange(),
                    "symbol": symbol,
                    "exchange_order_id": entry_order_id or None,
                    "side": side,
                    "quantity": entry_quantity,
                    "price": entry_price,
                    "fee_amount": entry_fill.fee,
                    "fee_currency": entry_fill.fee_currency or None,
                    "exchange_fill_id": entry_fill.trade_ids[0] if entry_fill.trade_ids else None,
                    "filled_at": entry_fill.filled_at,
                    "reference_price": entry_fill.reference_price,
                    "slippage_bps": entry_fill.slippage_bps,
                    "mark_price": entry_fill.mark_price,
                    "trigger_price": entry_fill.trigger_price,
                    "price_source": entry_fill.price_source.value,
                    "quantity_source": entry_fill.quantity_source.value,
                    "fee_source": entry_fill.fee_source.value,
                    "fee_currency": entry_fill.fee_currency,
                    "raw_payload": entry_fill.as_record(),
                })
                self.state_manager.record_trading_event(
                    "ORDER_FILLED",
                    f"order_filled:{self.config.exchange.primary_exchange()}:{entry_order_id}:{entry_price}:{entry_quantity}",
                    exchange=self.config.exchange.primary_exchange(),
                    trade_id=entry_order_id or None,
                    order_id=order_ledger_id,
                    symbol=symbol,
                    payload=entry_fill.as_record(),
                )

                # 6. حفظ الصفقة
                fee_result = self.fee_calculator.calculate(
                    position_size=notional_usd
                )
                trade_record = {
                    "id": entry_order_id,
                    "symbol": symbol,
                    "direction": str(action_val).upper(),
                    # ✅ إصلاح: عمود "mode" مطلوب من App.jsx (لوحة المتابعة) في
                    # استعلام SELECT الخاص بجدول trades ولم يكن يُحفَظ أبداً —
                    # كان سيسبب فراغاً دائماً في هذا العمود بالواجهة.
                    "mode": str(self.config.active_mode),
                    "strategy": strategy,
                    "strategy_subtype": strategy_subtype,
                    "signal_id": signal_id,
                    "signal_confidence": signal_result.get("confidence", 0.0),
                    "rule_score": signal_result.get("rule_score", signal_result.get("confidence", 0.0)),
                    "signal_reason": signal_result.get("reason", ""),
                    "exchange": self.config.exchange.primary_exchange(),
                    "entry_price": entry_price,
                    "entry_order_id": entry_order_id,
                    "entry_client_order_id": order.get("clientOrderId"),
                    "stop_algo_id": protection_ids[0] if len(protection_ids) > 0 else None,
                    "take_profit_algo_id": protection_ids[1] if len(protection_ids) > 1 else None,
                    "take_profit_1_algo_id": protection_ids[1] if len(protection_ids) > 1 else None,
                    "take_profit_2_algo_id": protection_ids[2] if len(protection_ids) > 2 else None,
                    "entry_price_source": entry_fill.price_source.value if entry_fill else "unconfirmed",
                    "entry_quantity_source": entry_fill.quantity_source.value if entry_fill else "unconfirmed",
                    "entry_fee_source": entry_fill.fee_source.value if entry_fill else "unconfirmed",
                    "stop_loss": stop_loss,
                    "atr_value": atr_value or None,
                    "atr_multiplier": atr_multiplier,
                    "stop_distance": abs(entry_price - stop_loss),
                    "risk_budget_usd": min(
                        float(getattr(risk_cfg, "max_risk_per_trade_usd", 0.0) or float("inf")),
                        self._current_balance * float(risk_cfg.max_risk_per_trade_pct) / 100.0,
                    ),
                    "take_profit_1": take_profit_1,
                    "take_profit_2": take_profit_2,
                    "size_usd": size_usd,
                    "margin_usd": size_usd,
                    "notional_usd": notional_usd,
                    "account_balance_at_entry": self._current_balance,
                    "entry_quantity": entry_quantity,
                    "remaining_quantity": entry_quantity,
                    "leverage": leverage,
                    "entry_fee": entry_fill.fee,
                    "entry_fee_currency": entry_fill.fee_currency or None,
                    "entry_filled_at": entry_fill.filled_at,
                    "entry_slippage_bps": entry_fill.slippage_bps,
                    "entry_mark_price": entry_fill.mark_price,
                    "entry_trigger_price": entry_fill.trigger_price,
                    "exit_fee": fee_result.exit_fee,
                    "status": "OPEN",
                    "confidence": signal_result.get("confidence", 0.0),
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "tp1_executed": False,
                    "trailing_active": False,
                    "trailing_stop": 0,
                    "breakeven_set": False,
                    "highest_price": entry_price,
                    "lowest_price": entry_price
                }
                if not self.state_manager.save_trade_state(trade_record):
                    raise RuntimeError("order executed but trade state could not be persisted")
                self.state_manager.record_strategy_signal({
                    "id": signal_id,
                    "idempotency_key": signal_idempotency_key,
                    "symbol": symbol,
                    "mode": str(self.config.active_mode),
                    "strategy": strategy,
                    "strategy_subtype": strategy_subtype,
                    "action": str(action_val).upper(),
                    "confidence": signal_result.get("confidence", 0.0),
                    "rule_score": signal_result.get("rule_score", signal_result.get("confidence", 0.0)),
                    "reason": signal_result.get("reason", ""),
                    "entry_price": entry_price,
                    "atr_value": atr_value or None,
                    "atr_multiplier": atr_multiplier,
                    "stop_distance": abs(entry_price - stop_loss),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit_1,
                    "risk_budget_usd": trade_record["risk_budget_usd"],
                    "status": "executed",
                    "trade_id": entry_order_id,
                })
                position = self.state_manager.reconstruct_position(trade_record)
                if position is None:
                    self._reconciliation_blocked_symbols.add(symbol)
                    raise RuntimeError("saved trade could not be reconstructed locally")
                self.position_manager.add_position(position)
                self.state_manager.record_trading_event(
                    "TRADE_OPENED",
                    f"trade_opened:{entry_order_id}",
                    exchange=self.config.exchange.primary_exchange(),
                    trade_id=entry_order_id or None,
                    order_id=order_ledger_id,
                    symbol=symbol,
                    payload={"status": "OPEN", "entry_price": entry_price},
                )
                # Notify only after the fill is confirmed and the trade state
                # is durably persisted; a signal alone is not a filled trade.
                await self.telegram.send_trade_opened(position)
                logger.info(f"✅ صفقة جديدة: {symbol} {side} @ {entry_price}")

            except Exception as e:
                if slot_reservation_id and not order_submitted:
                    self.state_manager.release_position_slot(
                        reservation_id=slot_reservation_id
                    )
                message = str(e)
                if "-2027" in message or "maximum allowable position" in message.lower():
                    self._reconciliation_blocked_symbols.add(symbol)
                    logger.warning(
                        "⚠️ Binance rejected a new position for {} due to the current position/leverage limit; "
                        "skipping this symbol for the remainder of this session: {}",
                        symbol,
                        message,
                    )
                    continue
                logger.error("❌ خطأ في %s: %s", symbol, message, exc_info=True)
                self.state_manager.record_learning_event({
                    "event_type": "execution_error",
                    "symbol": symbol,
                    "strategy": locals().get("strategy"),
                    "strategy_subtype": locals().get("strategy_subtype"),
                    "error_code": type(e).__name__,
                    "error_message": message[:2000],
                    "error_tags": [
                        tag for tag, matched in (
                            ("exchange_rejection", "binance" in message.lower()),
                            ("risk_gate", "risk" in message.lower()),
                            ("reconciliation", "reconcil" in message.lower()),
                            ("data_quality", "candle" in message.lower()),
                        ) if matched
                    ],
                    "features": {"execution_enabled": self.config.trading_execution_enabled},
                })
                cycle_errors.append(f"{symbol}: {type(e).__name__}: {message}")
                await self.telegram.send_error(f"Cycle Error [{symbol}]: {message}")

        if cycle_errors:
            raise RuntimeError("market cycle failed: " + " | ".join(cycle_errors))

    def _calculate_position_size(
        self,
        entry_price: float | None = None,
        stop_loss: float | None = None,
        leverage: int | None = None,
        account_balance: float | None = None,
    ) -> float:
        """Return margin sized by stop distance, capped by position percentage."""
        try:
            initial = float(account_balance if account_balance is not None else self._current_balance)
            if initial <= 0:
                raise ValueError("balance unavailable")
            max_margin = initial * float(self.config.risk.max_position_pct) / 100.0
            if not (
                entry_price
                and stop_loss
                and leverage
                and float(entry_price) > 0
                and float(stop_loss) > 0
                and float(leverage) > 0
            ):
                raise ValueError("entry, stop-loss, and leverage are required")
            stop_distance = abs(float(entry_price) - float(stop_loss)) / float(entry_price)
            configured_usd = float(getattr(self.config.risk, "max_risk_per_trade_usd", 0.0) or 0.0)
            percentage_budget = initial * float(self.config.risk.max_risk_per_trade_pct) / 100.0
            risk_budget = min(configured_usd, percentage_budget) if configured_usd > 0 else percentage_budget
            if stop_distance <= 0:
                raise ValueError("stop-loss distance must be positive")
            risk_sized_margin = risk_budget / (stop_distance * float(leverage))
            return round(max(0.0, min(max_margin, risk_sized_margin)), 2)
        except Exception as error:
            # Fail closed: a sizing/configuration failure must never fall back
            # to a live order amount, as happened in the historical US trade.
            logger.error("Position sizing failed; refusing entry: %s", error)
            return 0.0

    async def run_forever(self, interval_seconds: int = 60) -> None:
        """Run direct exchange polling and the real heartbeat loop."""
        max_cycles = int(os.environ.get("APEX_RUN_CYCLES", 0) or 0)
        single_cycle = max_cycles > 0

        needs_execution_lease = bool(self.config.trading_execution_enabled)
        if needs_execution_lease and not self.state_manager.acquire_execution_lease():
            logger.warning("⏳ Another execution owner is active; skipping this run")
            return

        heartbeat_task = None

        try:
            await self.initialize()
            if self.config.universe_refresh_only:
                logger.info("✅ Exiting after Universe refresh-only run")
                return
            heartbeat_task = asyncio.create_task(
                self.start_heartbeat_loop(interval_seconds=10)
            )
            cycles_done = 0
            while True:
                if self.state_manager.lease_lost:
                    raise RuntimeError("execution lease lost; refusing further trading cycles")
                await self.process_market_cycle()
                cycles_done += 1
                await self.state_manager.sync_trade_counters()
                await self.state_manager.mark_cycle_completed()
                if single_cycle and cycles_done >= max_cycles:
                    logger.info(f"✅ اكتمل {max_cycles} دورة(ات) — خروج من APEX_RUN_CYCLES={max_cycles}")
                    break
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            # ✅ كتابة حالة الخروج واجبة — تضمن ظهور البيانات حتى في الدورة الواحدة
            await self.state_manager.update_heartbeat()
            await self.state_manager.mark_bot_stopped()
            await self.shutdown()
            if needs_execution_lease:
                self.state_manager.release_execution_lease()

    async def shutdown(self) -> None:
        logger.info("Shutdown...")
        try:
            await self.state_manager.mark_bot_stopped()
        except Exception:
            pass
        # ✅ إغلاق موارد الـ exchange لتجنب تحذير unclosed connector
        try:
            await self.exchange.close()
        except Exception:
            pass
        try:
            await self.market_data.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — يُستدعى عند `python -m bot.main`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import sys

    # إعادة توجيه loguru إلى stdout حتى تظهر في سجلات الـ workflow
    from loguru import logger as _logger
    _logger.remove()
    _logger.add(
        sys.stdout,
        format="<level>{level}</level> | {message}",
        level="INFO",
        colorize=False,
    )

    async def _main():
        _logger.info("🚀 بدء تشغيل APEX TRADER...")
        bot = ApexTraderBot()
        try:
            # GitHub Actions may expose an optional input as an empty string.
            # Treat blank/invalid values as the safe one-minute default.
            raw_interval = (os.getenv("APEX_CYCLE_INTERVAL_SECONDS") or "60").strip()
            try:
                interval_seconds = int(raw_interval)
            except ValueError:
                _logger.warning(
                    f"⚠️ قيمة APEX_CYCLE_INTERVAL_SECONDS غير صالحة ({raw_interval!r})؛ "
                    "سيتم استخدام 60 ثانية"
                )
                interval_seconds = 60
            if interval_seconds < 1:
                _logger.warning("⚠️ يجب أن يكون الفاصل موجباً؛ سيتم استخدام 60 ثانية")
                interval_seconds = 60
            await bot.run_forever(interval_seconds=interval_seconds)
        except KeyboardInterrupt:
            _logger.info("⛔ توقف يدوياً")
        except Exception as e:
            _logger.error("❌ خطأ fatal: %s", e, exc_info=True)
            raise

    asyncio.run(_main())
