"""Safe async exchange adapter for Binance USD-M testnet/live.

Live trading is denied unless ALLOW_LIVE_TRADING=true is explicitly set.
This adapter intentionally rejects unsupported primary exchanges instead of
silently mixing data from one exchange with orders on another.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
import pandas as pd
from loguru import logger

from bot.core.provenance import FillDetails, FieldSource, QueryResult


class ExchangeSafetyError(RuntimeError):
    """Raised when an order would violate a local safety invariant."""


class ExchangeManager:
    def __init__(self, config: Optional[Any] = None):
        self.config = config
        exchange_cfg = getattr(config, "exchange", None)
        primary_getter = getattr(exchange_cfg, "primary_exchange", None)
        self.primary_exchange = str(primary_getter() if callable(primary_getter) else "binance").lower()
        if self.primary_exchange != "binance":
            raise ExchangeSafetyError(
                "Only Binance is enabled by this adapter; configure an explicit Bybit adapter first"
            )

        self.api_key = getattr(exchange_cfg, "binance_api_key", "") or os.getenv("BINANCE_API_KEY", "")
        self.secret_key = getattr(exchange_cfg, "binance_secret_key", "") or os.getenv("BINANCE_SECRET_KEY", "")
        self.is_testnet = bool(getattr(exchange_cfg, "binance_testnet", True))
        self.allow_live = os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes", "on"}
        configured_execution = getattr(config, "trading_execution_enabled", None)
        configured_entries = getattr(config, "allow_new_entries", None)
        self._execution_enabled = (
            bool(configured_execution)
            if configured_execution is not None
            else os.getenv("TRADING_EXECUTION_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._allow_new_entries = (
            bool(configured_entries)
            if configured_entries is not None
            else os.getenv("ALLOW_NEW_ENTRIES", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        if not self.is_testnet and not self.allow_live:
            raise ExchangeSafetyError(
                "Live trading is disabled. Set ALLOW_LIVE_TRADING=true only in a protected environment"
            )

        self._exchange: Optional[ccxt.Exchange] = None
        self._markets_loaded = False
        self._open_protection_orders: Dict[str, set[str]] = {}
        self._init_exchange()

    def _init_exchange(self) -> None:
        params: Dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {"defaultType": "future", "adjustForTimeDifference": True},
        }
        if self.api_key and self.secret_key:
            params.update({"apiKey": self.api_key, "secret": self.secret_key})
        self._exchange = ccxt.binanceusdm(params)
        if self.is_testnet:
            self._exchange.set_sandbox_mode(True)
            logger.info("Binance USD-M adapter initialized in TESTNET mode")
        else:
            logger.warning("Binance USD-M LIVE mode explicitly enabled")

    async def _ensure_ready(self) -> ccxt.Exchange:
        if self._exchange is None:
            raise ExchangeSafetyError("Exchange is not initialized")
        if not self._markets_loaded:
            await self._exchange.load_markets()
            self._markets_loaded = True
        return self._exchange

    def _assert_execution_allowed(self, operation: str, *, new_entry: bool = False) -> None:
        """Fail closed before any account-mutating exchange request."""
        enabled = getattr(self, "_execution_enabled", True)
        if not enabled:
            raise ExchangeSafetyError(
                f"{operation} blocked: TRADING_EXECUTION_ENABLED is false"
            )
        if new_entry and not getattr(self, "_allow_new_entries", True):
            raise ExchangeSafetyError(
                f"{operation} blocked: ALLOW_NEW_ENTRIES is false"
            )

    @staticmethod
    def _finite_positive(value: Any, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ExchangeSafetyError(f"{field} must be numeric") from exc
        if not math.isfinite(result) or result <= 0:
            raise ExchangeSafetyError(f"{field} must be finite and positive")
        return result

    async def _format_amount(self, symbol: str, amount: float) -> float:
        exchange = await self._ensure_ready()
        market = exchange.market(symbol)
        formatted = float(exchange.amount_to_precision(symbol, amount))
        minimum = (market.get("limits", {}).get("amount", {}) or {}).get("min")
        if minimum is not None and formatted < float(minimum):
            raise ExchangeSafetyError(f"amount {formatted} is below minimum {minimum} for {symbol}")
        return formatted

    async def _format_price(self, symbol: str, price: float) -> float:
        exchange = await self._ensure_ready()
        formatted = float(exchange.price_to_precision(symbol, price))
        return self._finite_positive(formatted, "price")

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            exchange = await self._ensure_ready()
            ticker = await exchange.fetch_ticker(symbol)

            def number(name: str) -> float:
                value = ticker.get(name)
                return float(value) if value is not None and math.isfinite(float(value)) else 0.0

            return {
                "last": number("last"),
                "bid": number("bid"),
                "ask": number("ask"),
                "source": FieldSource.EXCHANGE_MARKET_DATA.value,
            }
        except Exception as exc:
            logger.error("get_ticker {} failed: {}", symbol, exc)
            return {
                "last": 0.0,
                "bid": 0.0,
                "ask": 0.0,
                "source": FieldSource.UNCONFIRMED.value,
            }

    async def fetch_liquid_symbols(self, limit: int = 20, quote: str = "USDT") -> list[Dict[str, Any]]:
        """Return active linear futures symbols ranked by real 24h quote volume."""
        exchange = await self._ensure_ready()
        tickers = await exchange.fetch_tickers()
        quote = quote.upper()
        excluded_bases = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USDP"}
        candidates: list[Dict[str, Any]] = []
        for symbol, market in exchange.markets.items():
            if not market.get("active", True) or not market.get("contract", False):
                continue
            if not market.get("linear", False) or str(market.get("quote", "")).upper() != quote:
                continue
            base = str(market.get("base", "")).upper()
            if base in excluded_bases:
                continue
            ticker = tickers.get(symbol) or {}
            info = ticker.get("info") or {}
            try:
                quote_volume = float(ticker.get("quoteVolume") or info.get("quoteVolume") or 0.0)
                last = float(ticker.get("last") or info.get("lastPrice") or 0.0)
                bid = float(ticker.get("bid") or info.get("bidPrice") or 0.0)
                ask = float(ticker.get("ask") or info.get("askPrice") or 0.0)
            except (TypeError, ValueError):
                continue
            if quote_volume <= 0 or last <= 0:
                continue
            mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else last
            # Unknown spread is treated conservatively, never as zero.
            spread_bps = ((ask - bid) / mid * 10000.0) if bid > 0 and ask >= bid else 50.0
            if spread_bps > 50.0:
                continue
            candidates.append({
                "symbol": symbol,
                "quote_volume_24h": quote_volume,
                "spread_bps": spread_bps,
                "liquidity_score": quote_volume / (1.0 + spread_bps / 10.0),
            })
        candidates.sort(key=lambda row: row["liquidity_score"], reverse=True)
        return candidates[: max(1, int(limit))]

    async def fetch_fill_details(self, order_id: str, symbol: str) -> FillDetails:
        """Resolve execution facts without substituting ticker prices."""
        exchange = await self._ensure_ready()
        order: Dict[str, Any] = {}
        try:
            order = await exchange.fetch_order(str(order_id), symbol)
        except Exception as exc:
            logger.warning("fetch_order failed for {}: {}", order_id, exc)

        filled = float(order.get("filled") or 0.0)
        average = float(order.get("average") or order.get("price") or 0.0)
        price_source = FieldSource.EXCHANGE_FILL if average > 0 else FieldSource.UNCONFIRMED
        quantity_source = FieldSource.EXCHANGE_FILL if filled > 0 else FieldSource.UNCONFIRMED
        fee = 0.0
        fee_source = FieldSource.UNCONFIRMED
        trade_ids: list[str] = []

        fee_info = order.get("fee") or {}
        fee_currency = str(fee_info.get("currency") or "").upper()
        fee_cost = float(fee_info.get("cost") or 0.0)
        if fee_cost >= 0 and fee_currency in {"USDT", "BUSD"}:
            fee, fee_source = fee_cost, FieldSource.EXCHANGE_FILL
        else:
            try:
                trades = await exchange.fetch_my_trades(symbol, limit=100)
                related = [t for t in trades if str(t.get("order") or "") == str(order_id)]
                if related:
                    currencies = {
                        str((t.get("fee") or {}).get("currency") or "").upper()
                        for t in related
                    }
                    if currencies.issubset({"USDT", "BUSD"}):
                        fee = sum(float((t.get("fee") or {}).get("cost") or 0.0) for t in related)
                        fee_source = FieldSource.EXCHANGE_FILL
                    trade_ids = [str(t.get("id")) for t in related if t.get("id")]
            except Exception as exc:
                logger.warning("fetch_my_trades failed for {}: {}", order_id, exc)

        return FillDetails(
            price=average,
            price_source=price_source,
            quantity=filled,
            quantity_source=quantity_source,
            fee=fee,
            fee_source=fee_source,
            order_id=str(order_id),
            trade_ids=tuple(trade_ids),
        )

    async def get_all_open_positions_result(self) -> QueryResult:
        """Distinguish an empty account from a failed position query."""
        try:
            exchange = await self._ensure_ready()
            positions = await exchange.fetch_positions()
            open_positions = [
                p for p in positions if abs(float(p.get("contracts") or 0)) > 0
            ]
            return QueryResult.from_items(open_positions)
        except Exception as exc:
            logger.critical("fetch_positions failed: {}", exc)
            return QueryResult.failed(exc)

    async def get_balance(self) -> float:
        try:
            exchange = await self._ensure_ready()
            balance = await exchange.fetch_balance()
            usdt = balance.get("USDT") or {}
            free = usdt.get("free")
            return float(free) if free is not None and math.isfinite(float(free)) else 0.0
        except Exception as exc:
            logger.error("get_balance failed: {}", exc)
            return 0.0

    async def get_ohlcv(self, symbol: str, timeframe: str = "5m", limit: int = 100) -> Optional[pd.DataFrame]:
        try:
            exchange = await self._ensure_ready()
            raw = await exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
            if not raw:
                return None
            frame = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
            for column in ["open", "high", "low", "close", "volume"]:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
            return frame if not frame.empty else None
        except Exception as exc:
            logger.error("get_ohlcv {} failed: {}", symbol, exc)
            return None

    async def _set_leverage(self, symbol: str, leverage: int) -> None:
        self._assert_execution_allowed("set_leverage", new_entry=True)
        exchange = await self._ensure_ready()
        if leverage < 1 or leverage > 125:
            raise ExchangeSafetyError("leverage is outside Binance USD-M bounds")
        await exchange.set_leverage(leverage, symbol)

    async def _create_protection(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_loss: float,
        take_profit: float,
        take_profit_2: Optional[float] = None,
        tp1_fraction: float = 0.5,
    ) -> set[str]:
        """Create Binance USD-M conditional protection through Algo Orders."""
        self._assert_execution_allowed("create_protection")
        exchange = await self._ensure_ready()
        close_side = "sell" if side == "buy" else "buy"
        market_id = str(exchange.market(symbol)["id"])
        ids: set[str] = set()
        orders = [("STOP_MARKET", amount, stop_loss, "sl")]
        if take_profit_2 is None:
            orders.append(("TAKE_PROFIT_MARKET", amount, take_profit, "tp"))
        else:
            if not 0 < tp1_fraction < 1:
                raise ExchangeSafetyError("tp1_fraction must be between 0 and 1")
            tp1_amount = amount * tp1_fraction
            tp2_amount = amount - tp1_amount
            orders.extend([
                ("TAKE_PROFIT_MARKET", tp1_amount, take_profit, "tp1"),
                ("TAKE_PROFIT_MARKET", tp2_amount, take_profit_2, "tp2"),
            ])
        for order_type, order_amount, trigger_price, label in orders:
            if hasattr(exchange, "amount_to_precision"):
                order_amount = await self._format_amount(symbol, order_amount)
            else:  # lightweight test doubles may not expose market precision APIs
                order_amount = float(order_amount)
            params = {
                "algoType": "CONDITIONAL",
                "symbol": market_id,
                "side": close_side.upper(),
                "type": order_type,
                "quantity": order_amount,
                "triggerPrice": trigger_price,
                "workingType": "CONTRACT_PRICE",
                "reduceOnly": "true",
                "clientAlgoId": f"apex-{label}-{int(exchange.milliseconds())}"[:36],
                "newOrderRespType": "ACK",
            }
            order = await exchange.request("algoOrder", "fapiPrivate", "POST", params)
            order_id = str(order.get("algoId") or order.get("orderId") or "")
            if not order_id:
                raise ExchangeSafetyError(f"{order_type} returned no algo id")
            ids.add(order_id)
        return ids

    async def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        stop_loss: float,
        take_profit: float,
        leverage: Optional[int] = None,
        client_order_id: Optional[str] = None,
        take_profit_2: Optional[float] = None,
        tp1_fraction: float = 0.5,
    ) -> Dict[str, Any]:
        self._assert_execution_allowed("place_order", new_entry=True)
        exchange = await self._ensure_ready()
        if side.lower() not in {"buy", "sell"}:
            raise ExchangeSafetyError("side must be buy or sell")
        amount = await self._format_amount(symbol, self._finite_positive(amount, "amount"))
        reference_price = await self._format_price(symbol, self._finite_positive(price, "price"))
        stop_loss = await self._format_price(symbol, self._finite_positive(stop_loss, "stop_loss"))
        take_profit = await self._format_price(symbol, self._finite_positive(take_profit, "take_profit"))
        if leverage is not None:
            await self._set_leverage(symbol, int(leverage))

        params: Dict[str, Any] = {"reduceOnly": False}
        if client_order_id:
            params["newClientOrderId"] = client_order_id[:36]
        entry = await exchange.create_order(symbol=symbol, type="market", side=side.lower(), amount=amount, params=params)
        entry_id = str(entry.get("id", ""))
        if not entry_id:
            raise ExchangeSafetyError("entry order returned no order id")

        try:
            protections = await self._create_protection(
                symbol,
                side.lower(),
                amount,
                stop_loss,
                take_profit,
                take_profit_2=take_profit_2,
                tp1_fraction=tp1_fraction,
            )
        except Exception as protection_error:
            logger.critical(f"Protection setup failed for {symbol}: {protection_error}")
            try:
                await self.reduce_only_close(symbol=symbol, amount=amount, reason="protection_failed")
                positions = await exchange.fetch_positions([symbol])
                remaining = next(
                    (p for p in positions if p.get("symbol") == symbol and abs(float(p.get("contracts") or 0)) > 0),
                    None,
                )
                if remaining is not None:
                    raise ExchangeSafetyError("rollback left an open position")
            except Exception as rollback_error:
                logger.critical(f"Emergency close failed for {symbol}: {rollback_error}")
            raise ExchangeSafetyError("entry was not accepted as protected") from protection_error

        self._open_protection_orders[entry_id] = protections
        return {
            **entry,
            "entry_price": float(entry.get("average") or entry.get("price") or reference_price),
            "filled_amount": float(entry.get("filled") or amount),
            "protection_order_ids": sorted(protections),
        }

    async def reduce_only_close(self, symbol: str, amount: float, reason: str = "manual") -> Dict[str, Any]:
        self._assert_execution_allowed("reduce_only_close")
        exchange = await self._ensure_ready()
        amount = await self._format_amount(symbol, self._finite_positive(amount, "amount"))
        positions = await exchange.fetch_positions([symbol])
        position = next((p for p in positions if p.get("symbol") == symbol and abs(float(p.get("contracts") or 0)) > 0), None)
        if position is None:
            return {}
        side = "sell" if position.get("side") == "long" else "buy"
        order = await exchange.create_order(symbol=symbol, type="market", side=side, amount=amount, params={"reduceOnly": True})
        logger.info("reduce-only close {} {} reason={}", symbol, amount, reason)
        return order or {}

    async def _cancel_protection_orders(self, symbol: str) -> None:
        """Cancel active Binance Algo Orders before closing a position."""
        self._assert_execution_allowed("cancel_protection_orders")
        exchange = await self._ensure_ready()
        market_id = str(exchange.market(symbol)["id"])
        try:
            algo_orders = await exchange.request(
                "openAlgoOrders", "fapiPrivate", "GET", {"symbol": market_id}
            )
        except Exception as exc:
            logger.warning("Unable to list Binance algo orders for {}: {}", symbol, exc)
            algo_orders = []
        for order in algo_orders or []:
            algo_id = order.get("algoId")
            if algo_id:
                try:
                    await exchange.request(
                        "algoOrder", "fapiPrivate", "DELETE",
                        {"symbol": market_id, "algoId": algo_id},
                    )
                except Exception as exc:
                    logger.warning("Unable to cancel algo order {} for {}: {}", algo_id, symbol, exc)

    async def close_position(self, symbol: str, position_id: str, reason: str, price: float) -> Dict[str, Any]:
        self._assert_execution_allowed("close_position")
        exchange = await self._ensure_ready()
        await self._cancel_protection_orders(symbol)
        positions = await exchange.fetch_positions([symbol])
        position = next((p for p in positions if p.get("symbol") == symbol and abs(float(p.get("contracts") or 0)) > 0), None)
        if position is None:
            return {}
        amount = abs(float(position.get("contracts") or 0))
        return await self.reduce_only_close(symbol, amount, reason=reason)

    async def close(self) -> None:
        if self._exchange is not None:
            try:
                await self._exchange.close()
            finally:
                self._exchange = None
