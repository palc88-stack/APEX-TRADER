import asyncio
from datetime import datetime
from typing import Dict, Optional

import ccxt.async_support as ccxt
import pandas as pd
from loguru import logger

from bot.config import config


class MarketDataManager:
    """
    جلب بيانات السوق من المنصة الأساسية.

    لا يتم استخدام Binance بشكل إجباري.
    """

    CACHE_SECONDS = 60

    def __init__(self):
        self._exchange: Optional[ccxt.Exchange] = None
        self._exchange_name = (
            config.exchange.primary_exchange()
        )
        self._cache: Dict[str, dict] = {}
        self._markets_loaded = False

        self._init_exchange()

    def _init_exchange(self) -> None:
        if self._exchange_name == "binance":
            self._exchange = ccxt.binanceusdm(
                {
                    "apiKey": config.exchange.binance_api_key,
                    "secret": config.exchange.binance_secret_key,
                    "enableRateLimit": True,
                    "timeout": 15000,
                    "options": {
                        "defaultType": "future",
                        "adjustForTimeDifference": True,
                    },
                }
            )

            if config.exchange.binance_testnet:
                self._exchange.set_sandbox_mode(True)

            logger.info(
                "✅ Market data exchange: Binance | testnet={}",
                config.exchange.binance_testnet,
            )
            return

        if self._exchange_name == "bybit":
            self._exchange = ccxt.bybit(
                {
                    "apiKey": config.exchange.bybit_api_key,
                    "secret": config.exchange.bybit_secret_key,
                    "enableRateLimit": True,
                    "timeout": 15000,
                    "options": {
                        "defaultType": "linear",
                        "adjustForTimeDifference": True,
                    },
                }
            )

            if config.exchange.bybit_testnet:
                self._exchange.set_sandbox_mode(True)

            logger.info(
                "✅ Market data exchange: Bybit | testnet={}",
                config.exchange.bybit_testnet,
            )
            return

        raise RuntimeError(
            f"Unsupported market data exchange: "
            f"{self._exchange_name}"
        )

    def _normalize_symbol(self, symbol: str) -> str:
        normalized = symbol.strip().upper()

        if (
            self._exchange_name == "bybit"
            and normalized.endswith("/USDT")
        ):
            return f"{normalized}:USDT"

        return normalized

    async def _load_markets(self) -> None:
        if self._exchange is None:
            raise RuntimeError(
                "Market data exchange is not initialized"
            )

        if not self._markets_loaded:
            await self._exchange.load_markets()
            self._markets_loaded = True

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> Optional[pd.DataFrame]:
        cache_key = (
            f"{self._exchange_name}:"
            f"{symbol}:{timeframe}:{limit}"
        )

        cached = self._get_from_cache(cache_key)

        if cached is not None:
            return cached

        try:
            await self._load_markets()

            if self._exchange is None:
                return None

            raw_data = await self._exchange.fetch_ohlcv(
                symbol=self._normalize_symbol(symbol),
                timeframe=timeframe,
                limit=limit,
            )

            if not raw_data:
                logger.warning(
                    "⚠️ No OHLCV data for {}",
                    symbol,
                )
                return None

            dataframe = pd.DataFrame(
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

            dataframe["timestamp"] = pd.to_datetime(
                dataframe["timestamp"],
                unit="ms",
                utc=True,
            )

            for column in [
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]:
                dataframe[column] = pd.to_numeric(
                    dataframe[column],
                    errors="coerce",
                )

            dataframe = (
                dataframe
                .dropna()
                .sort_values("timestamp")
                .reset_index(drop=True)
            )

            if not self._validate_ohlcv(
                dataframe,
                symbol,
            ):
                return None

            self._save_to_cache(
                cache_key,
                dataframe,
            )

            return dataframe

        except ccxt.BadSymbol:
            logger.warning(
                "⚠️ Invalid symbol {}",
                symbol,
            )
            return None

        except ccxt.NetworkError as error:
            logger.error(
                "❌ Network error for {}: {}",
                symbol,
                error,
            )
            return None

        except ccxt.ExchangeError as error:
            logger.error(
                "❌ Exchange error for {}: {}",
                symbol,
                error,
            )
            return None

        except Exception as error:
            logger.exception(
                "❌ OHLCV error for {}: {}",
                symbol,
                error,
            )
            return None

    def _validate_ohlcv(
        self,
        dataframe: pd.DataFrame,
        symbol: str,
    ) -> bool:
        if dataframe.empty:
            logger.warning(
                "⚠️ Empty OHLCV data for {}",
                symbol,
            )
            return False

        required = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        if any(
            column not in dataframe.columns
            for column in required
        ):
            return False

        if (dataframe["close"] <= 0).any():
            logger.warning(
                "⚠️ Invalid close price for {}",
                symbol,
            )
            return False

        invalid_candles = (
            (dataframe["high"] < dataframe["low"])
            | (dataframe["high"] < dataframe["open"])
            | (dataframe["high"] < dataframe["close"])
            | (dataframe["low"] > dataframe["open"])
            | (dataframe["low"] > dataframe["close"])
        )

        if invalid_candles.any():
            logger.warning(
                "⚠️ Invalid candles for {}",
                symbol,
            )
            return False

        return True

    def _get_from_cache(
        self,
        key: str,
    ) -> Optional[pd.DataFrame]:
        cached = self._cache.get(key)

        if cached is None:
            return None

        age = (
            datetime.utcnow() - cached["time"]
        ).total_seconds()

        if age > self.CACHE_SECONDS:
            self._cache.pop(key, None)
            return None

        return cached["data"].copy()

    def _save_to_cache(
        self,
        key: str,
        dataframe: pd.DataFrame,
    ) -> None:
        self._cache[key] = {
            "data": dataframe.copy(),
            "time": datetime.utcnow(),
        }

    async def get_multiple_ohlcv(
        self,
        symbols: list,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> Dict[str, pd.DataFrame]:
        tasks = [
            self.get_ohlcv(
                symbol,
                timeframe,
                limit,
            )
            for symbol in symbols
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        result_data = {}

        for symbol, result in zip(
            symbols,
            results,
        ):
            if isinstance(result, pd.DataFrame):
                result_data[symbol] = result
            elif isinstance(result, Exception):
                logger.error(
                    "❌ Error loading {}: {}",
                    symbol,
                    result,
                )

        return result_data

    async def get_market_info(
        self,
        symbol: str,
    ) -> dict:
        try:
            await self._load_markets()

            if self._exchange is None:
                return {}

            ticker = await self._exchange.fetch_ticker(
                self._normalize_symbol(symbol)
            )

            return {
                "symbol": symbol,
                "last_price": float(
                    ticker.get("last") or 0
                ),
                "volume_24h": float(
                    ticker.get("baseVolume") or 0
                ),
                "change_24h_pct": float(
                    ticker.get("percentage") or 0
                ),
                "high_24h": float(
                    ticker.get("high") or 0
                ),
                "low_24h": float(
                    ticker.get("low") or 0
                ),
                "timestamp": ticker.get(
                    "timestamp",
                    0,
                ),
            }

        except Exception as error:
            logger.error(
                "❌ Market info error for {}: {}",
                symbol,
                error,
            )
            return {}

    async def close(self) -> None:
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None
