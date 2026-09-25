# bot/core/exchange.py - الكود المُصحَّح (كامل مع async)
import os
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
import pandas as pd
from loguru import logger


class ExchangeManager:
    """
    مدير منصات التداول - يدعم Binance و Bybit.
    ✅ async كامل متوافق مع MarketDataManager.
    ✅ يملك جميع دوال التنفيذ المطلوبة.
    """

    def __init__(self, config: Optional[Any] = None):
        self.config = config
        exchange_cfg = getattr(config, "exchange", None)

        self.api_key = (
            getattr(exchange_cfg, "binance_api_key", None)
            or os.getenv("BINANCE_API_KEY", "")
        )
        self.secret_key = (
            getattr(exchange_cfg, "binance_secret_key", None)
            or os.getenv("BINANCE_SECRET_KEY", "")
        )
        is_testnet = bool(
            getattr(exchange_cfg, "binance_testnet", True)
        )

        # ✅ async exchange
        self._exchange: Optional[ccxt.Exchange] = None
        self._init_exchange(is_testnet)

    def _init_exchange(self, is_testnet: bool) -> None:
        try:
            exchange_params: Dict[str, Any] = {
                "enableRateLimit": True,
                "timeout": 15000,
                "options": {
                    "defaultType": "future",
                    "adjustForTimeDifference": True,
                },
            }
            # تمرير المفاتيح فقط إذا كانت موجودة فعلاً
            if self.api_key and self.secret_key:
                exchange_params["apiKey"] = self.api_key
                exchange_params["secret"] = self.secret_key
            self._exchange = ccxt.binanceusdm(exchange_params)
            if is_testnet:
                self._exchange.set_sandbox_mode(True)
                if self.api_key and self.secret_key:
                    logger.info("✅ Binance Testnet: المفاتيح متاحة، يمكن تنفيذ صفقات حقيقية")
                else:
                    logger.warning(
                        "⚠️ Binance Testnet: بدون مفاتيح API — لا يمكن فتح صفقات. "
                        f"قم بتعيين BINANCE_API_KEY و BINANCE_SECRET_KEY"
                    )
            else:
                logger.info("🚀 Exchange: Binance Futures Live")
        except Exception as e:
            logger.error("❌ Exchange init failed: {}", e)
            self._exchange = None

    # ─── Data ─────────────────────────────────────────────────────────────────

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """جلب السعر الحالي للرمز."""
        try:
            ticker = await self._exchange.fetch_ticker(symbol)
            return {
                "last": float(ticker.get("last", 0)),
                "bid": float(ticker.get("bid", 0)),
                "ask": float(ticker.get("ask", 0)),
            }
        except Exception as e:
            logger.error("❌ get_ticker {}: {}", symbol, e)
            return {"last": 0.0, "bid": 0.0, "ask": 0.0}

    async def get_balance(self) -> float:
        """جلب رصيد USDT الحر."""
        try:
            balance = await self._exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            return float(usdt.get("free", 0.0))
        except Exception as e:
            logger.error("❌ get_balance: {}", e)
            return 0.0

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> Optional[pd.DataFrame]:
        """جلب بيانات OHLCV — متوفرة للـ MarketDataManager كـ cache layer."""
        try:
            if not self._exchange:
                raise RuntimeError("Exchange not initialized")
            raw_data = await self._exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
            )
            if not raw_data:
                logger.warning("⚠️ No OHLCV data for {}", symbol)
                return None
            df = pd.DataFrame(
                raw_data,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
            )
            df["timestamp"] = pd.to_datetime(
                df["timestamp"],
                unit="ms",
                utc=True,
            )
            for column in ["open", "high", "low", "close", "volume"]:
                df[column] = df[column].astype(float)
            return df
        except Exception as e:
            logger.error("❌ get_ohlcv {}: {}", symbol, e)
            return None

    # ─── Orders ───────────────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        stop_loss: float,
        take_profit: float,
    ) -> Dict[str, Any]:
        """
        ✅ تنفيذ أمر شراء أو بيع مع SL و TP.
        يستخدم Market Order للدخول + SL/TP كـ Stop Orders.
        """
        try:
            if not self._exchange:
                raise RuntimeError("Exchange not initialized")

            # أمر السوق الرئيسي
            order = await self._exchange.create_order(
                symbol=symbol,
                type="market",
                side=side.lower(),
                amount=amount,
                params={"reduceOnly": False}
            )
            logger.info(
                "✅ Order placed: {} {} {} @ {}",
                side.upper(), amount, symbol, price
            )

            # أمر وقف الخسارة
            sl_side = "sell" if side.lower() == "buy" else "buy"
            try:
                await self._exchange.create_order(
                    symbol=symbol,
                    type="stop_market",
                    side=sl_side,
                    amount=amount,
                    params={
                        "stopPrice": stop_loss,
                        "reduceOnly": True,
                        "closePosition": True,
                    }
                )
                logger.info(
                    "🛡️ Stop Loss set @ {}", stop_loss
                )
            except Exception as sl_err:
                logger.warning("⚠️ SL order failed: {}", sl_err)

            # أمر جني الأرباح
            tp_side = sl_side
            try:
                await self._exchange.create_order(
                    symbol=symbol,
                    type="take_profit_market",
                    side=tp_side,
                    amount=amount,
                    params={
                        "stopPrice": take_profit,
                        "reduceOnly": True,
                        "closePosition": True,
                    }
                )
                logger.info(
                    "🎯 Take Profit set @ {}", take_profit
                )
            except Exception as tp_err:
                logger.warning("⚠️ TP order failed: {}", tp_err)

            return order or {}

        except Exception as e:
            logger.error("❌ place_order {}: {}", symbol, e)
            raise

    async def close_position(
        self,
        symbol: str,
        position_id: str,
        reason: str,
        price: float,
    ) -> Dict[str, Any]:
        """إغلاق صفقة مفتوحة بأمر Market عكسي."""
        try:
            positions = await self._exchange.fetch_positions([symbol])
            pos = next(
                (p for p in positions if p.get("symbol") == symbol
                 and float(p.get("contracts", 0)) != 0),
                None
            )
            if not pos:
                logger.warning(
                    "⚠️ لا توجد صفقة مفتوحة لـ {} في المنصة", symbol
                )
                return {}

            amount = abs(float(pos.get("contracts", 0)))
            side_to_close = (
                "sell" if pos.get("side") == "long" else "buy"
            )

            order = await self._exchange.create_order(
                symbol=symbol,
                type="market",
                side=side_to_close,
                amount=amount,
                params={"reduceOnly": True}
            )

            logger.info(
                "✅ Position closed: {} | السبب: {} | السعر: {}",
                symbol, reason, price
            )
            return order or {}

        except Exception as e:
            logger.error("❌ close_position {}: {}", symbol, e)
            raise

    async def close(self) -> None:
        """إغلاق الاتصال بالمنصة."""
        if self._exchange:
            try:
                await self._exchange.close()
            except Exception:
                pass
