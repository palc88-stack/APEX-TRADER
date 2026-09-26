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

            return {"last": number("last"), "bid": number("bid"), "ask": number("ask")}
        except Exception as exc:
            logger.error("get_ticker {} failed: {}", symbol, exc)
            return {"last": 0.0, "bid": 0.0, "ask": 0.0}

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
        exchange = await self._ensure_ready()
        if leverage < 1 or leverage > 125:
            raise ExchangeSafetyError("leverage is outside Binance USD-M bounds")
        await exchange.set_leverage(leverage, symbol)

    async def _create_protection(self, symbol: str, side: str, amount: float, stop_loss: float, take_profit: float) -> set[str]:
        exchange = await self._ensure_ready()
        close_side = "sell" if side == "buy" else "buy"
        ids: set[str] = set()
        for order_type, stop_price in (("stop_market", stop_loss), ("take_profit_market", take_profit)):
            order = await exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=close_side,
                amount=amount,
                params={"stopPrice": stop_price, "reduceOnly": True},
            )
            order_id = str(order.get("id", ""))
            if not order_id:
                raise ExchangeSafetyError(f"{order_type} returned no order id")
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
    ) -> Dict[str, Any]:
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
            protections = await self._create_protection(symbol, side.lower(), amount, stop_loss, take_profit)
        except Exception as protection_error:
            logger.critical("Protection setup failed for %s: %s", symbol, protection_error)
            try:
                await self.reduce_only_close(symbol=symbol, amount=amount, reason="protection_failed")
            except Exception as rollback_error:
                logger.critical("Emergency close failed for %s: %s", symbol, rollback_error)
            raise ExchangeSafetyError("entry was not accepted as protected") from protection_error

        self._open_protection_orders[entry_id] = protections
        return {
            **entry,
            "entry_price": float(entry.get("average") or entry.get("price") or reference_price),
            "filled_amount": float(entry.get("filled") or amount),
            "protection_order_ids": sorted(protections),
        }

    async def reduce_only_close(self, symbol: str, amount: float, reason: str = "manual") -> Dict[str, Any]:
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
        exchange = await self._ensure_ready()
        try:
            open_orders = await exchange.fetch_open_orders(symbol)
        except Exception as exc:
            logger.warning("Unable to list open protection orders for {}: {}", symbol, exc)
            return
        for order in open_orders:
            if order.get("reduceOnly") or order.get("type") in {"stop_market", "take_profit_market"}:
                order_id = order.get("id")
                if order_id:
                    try:
                        await exchange.cancel_order(order_id, symbol)
                    except Exception as exc:
                        logger.warning("Unable to cancel order {}: {}", order_id, exc)

    async def close_position(self, symbol: str, position_id: str, reason: str, price: float) -> Dict[str, Any]:
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
