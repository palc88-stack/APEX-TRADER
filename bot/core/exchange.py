import time
from typing import Dict, List, Optional

import ccxt.async_support as ccxt
from loguru import logger

from bot.config import config


class ExchangeManager:
    """
    مدير متعدد المنصات.

    حالياً:
        TRADING_EXCHANGES=binance

    مستقبلاً:
        TRADING_EXCHANGES=binance,bybit

    يتم تشغيل Binance فقط للتداول في هذه النسخة.
    Bybit يمكن تهيئته، لكن لا يتم فتح صفقات عليه
    حتى تتم إضافة واختبار أوامر الحماية الخاصة به.
    """

    def __init__(self):
        self._exchanges: Dict[str, ccxt.Exchange] = {}
        self._markets_loaded: Dict[str, bool] = {}
        self._latency: Dict[str, float] = {}

        self.enabled_exchanges = (
            config.exchange.enabled_exchanges()
        )

        if not self.enabled_exchanges:
            raise RuntimeError(
                "No exchange with complete credentials is enabled"
            )

        self.active_exchange = (
            self.enabled_exchanges[0]
        )

        self._init_exchanges()

    def _init_exchanges(self) -> None:
        for exchange_name in self.enabled_exchanges:
            try:
                if exchange_name == "binance":
                    exchange = ccxt.binanceusdm(
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
                        exchange.set_sandbox_mode(True)

                elif exchange_name == "bybit":
                    exchange = ccxt.bybit(
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
                        exchange.set_sandbox_mode(True)

                else:
                    logger.warning(
                        "Unsupported exchange skipped: {}",
                        exchange_name,
                    )
                    continue

                self._exchanges[exchange_name] = exchange
                self._markets_loaded[exchange_name] = False
                self._latency[exchange_name] = 0.0

                logger.info(
                    "✅ Exchange initialized: {}",
                    exchange_name,
                )

            except Exception as error:
                logger.exception(
                    "❌ Failed to initialize {}: {}",
                    exchange_name,
                    error,
                )

        if not self._exchanges:
            raise RuntimeError(
                "All configured exchanges failed to initialize"
            )

        logger.info(
            "🏦 Active exchanges: {}",
            ", ".join(self._exchanges.keys()),
        )

    def available_exchanges(self) -> List[str]:
        return list(self._exchanges.keys())

    def _resolve_exchange(
        self,
        exchange_name: Optional[str] = None,
    ) -> str:
        selected = (
            exchange_name or self.active_exchange
        ).lower()

        if selected not in self._exchanges:
            raise RuntimeError(
                f"Exchange is not initialized: {selected}"
            )

        return selected

    def get_exchange(
        self,
        exchange_name: Optional[str] = None,
    ) -> ccxt.Exchange:
        selected = self._resolve_exchange(
            exchange_name
        )
        return self._exchanges[selected]

    def normalize_symbol(
        self,
        symbol: str,
        exchange_name: Optional[str] = None,
    ) -> str:
        selected = self._resolve_exchange(
            exchange_name
        )
        normalized = symbol.strip().upper()

        if (
            selected == "bybit"
            and normalized.endswith("/USDT")
        ):
            return f"{normalized}:USDT"

        return normalized

    async def _load_markets(
        self,
        exchange_name: Optional[str] = None,
    ) -> None:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]

        if not self._markets_loaded[selected]:
            await exchange.load_markets()
            self._markets_loaded[selected] = True

    async def check_connection(
        self,
        exchange_name: Optional[str] = None,
    ) -> bool:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]

        try:
            started = time.monotonic()

            await self._load_markets(selected)
            await exchange.fetch_time()

            latency = (
                time.monotonic() - started
            ) * 1000

            self._latency[selected] = latency

            logger.info(
                "✅ {} connection OK | latency={:.0f}ms",
                selected,
                latency,
            )

            return True

        except ccxt.AuthenticationError as error:
            logger.error(
                "❌ {} authentication failed: {}",
                selected,
                error,
            )
            return False

        except ccxt.NetworkError as error:
            logger.error(
                "❌ {} network error: {}",
                selected,
                error,
            )
            return False

        except ccxt.ExchangeError as error:
            logger.error(
                "❌ {} exchange error: {}",
                selected,
                error,
            )
            return False

        except Exception as error:
            logger.exception(
                "❌ {} connection error: {}",
                selected,
                error,
            )
            return False

    async def check_all_connections(self) -> Dict[str, bool]:
        results = {}

        for exchange_name in self.available_exchanges():
            results[exchange_name] = (
                await self.check_connection(exchange_name)
            )

        return results

    async def get_latency(
        self,
        exchange_name: Optional[str] = None,
    ) -> float:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]

        try:
            started = time.monotonic()
            await exchange.fetch_time()

            latency = (
                time.monotonic() - started
            ) * 1000

            self._latency[selected] = latency
            return latency

        except Exception:
            return 999.0

    async def get_balance(
        self,
        exchange_name: Optional[str] = None,
    ) -> float:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]

        try:
            balance = await exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            free_balance = usdt.get("free", 0.0)

            return float(free_balance or 0.0)

        except ccxt.AuthenticationError:
            logger.error(
                "❌ Authentication failed on {}",
                selected,
            )
            return 0.0

        except Exception as error:
            logger.error(
                "❌ Balance error on {}: {}",
                selected,
                error,
            )
            return 0.0

    async def get_ticker(
        self,
        symbol: str,
        exchange_name: Optional[str] = None,
    ) -> dict:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )

        try:
            ticker = await exchange.fetch_ticker(
                market_symbol
            )

            return {
                "last": float(ticker.get("last") or 0),
                "bid": float(ticker.get("bid") or 0),
                "ask": float(ticker.get("ask") or 0),
                "volume": float(
                    ticker.get("baseVolume") or 0
                ),
                "change_pct": float(
                    ticker.get("percentage") or 0
                ),
                "high": float(ticker.get("high") or 0),
                "low": float(ticker.get("low") or 0),
            }

        except ccxt.BadSymbol:
            logger.warning(
                "⚠️ Invalid symbol {} on {}",
                symbol,
                selected,
            )
            return {}

        except Exception as error:
            logger.error(
                "❌ Ticker error {} on {}: {}",
                symbol,
                selected,
                error,
            )
            return {}

    async def get_orderbook(
        self,
        symbol: str,
        limit: int = 10,
        exchange_name: Optional[str] = None,
    ) -> Optional[dict]:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )

        try:
            orderbook = await exchange.fetch_order_book(
                market_symbol,
                limit=limit,
            )

            return {
                "bids": orderbook.get("bids", []),
                "asks": orderbook.get("asks", []),
                "timestamp": orderbook.get(
                    "timestamp",
                    0,
                ),
            }

        except Exception as error:
            logger.debug(
                "Orderbook error {} on {}: {}",
                symbol,
                selected,
                error,
            )
            return None

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        exchange_name: Optional[str] = None,
    ) -> bool:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )

        try:
            await exchange.set_leverage(
                leverage,
                market_symbol,
            )
            return True

        except ccxt.ExchangeError as error:
            logger.warning(
                "⚠️ Cannot set leverage for {} on {}: {}",
                symbol,
                selected,
                error,
            )
            return False

    async def _create_binance_protection_orders(
        self,
        exchange: ccxt.Exchange,
        symbol: str,
        close_side: str,
        amount: float,
        stop_loss: float,
        take_profit: float,
    ) -> None:
        await exchange.create_order(
            symbol,
            "STOP_MARKET",
            close_side,
            amount,
            None,
            {
                "stopPrice": stop_loss,
                "reduceOnly": True,
                "closePosition": True,
                "workingType": "MARK_PRICE",
            },
        )

        await exchange.create_order(
            symbol,
            "TAKE_PROFIT_MARKET",
            close_side,
            amount,
            None,
            {
                "stopPrice": take_profit,
                "reduceOnly": True,
                "closePosition": True,
                "workingType": "MARK_PRICE",
            },
        )

    async def place_order(
        self,
        symbol: str,
        direction: str,
        size_usd: float,
        leverage: int,
        stop_loss: float,
        take_profit: float,
        exchange_name: Optional[str] = None,
    ) -> Optional[dict]:
        selected = self._resolve_exchange(
            exchange_name
        )

        if selected != "binance":
            raise RuntimeError(
                "Trading is currently enabled for Binance only. "
                "Bybit is initialized but disabled until its "
                "SL/TP implementation is tested."
            )

        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )

        entry_side = (
            "buy"
            if direction.lower() == "long"
            else "sell"
        )

        close_side = (
            "sell"
            if entry_side == "buy"
            else "buy"
        )

        amount = 0.0

        try:
            await self._load_markets(selected)

            await self.set_leverage(
                symbol,
                leverage,
                selected,
            )

            ticker = await exchange.fetch_ticker(
                market_symbol
            )
            current_price = float(
                ticker.get("last") or 0
            )

            if current_price <= 0:
                raise RuntimeError(
                    f"Invalid price for {symbol}"
                )

            market = exchange.market(market_symbol)

            raw_amount = (
                size_usd * leverage
            ) / current_price

            amount = float(
                exchange.amount_to_precision(
                    market_symbol,
                    raw_amount,
                )
            )

            minimum = (
                market.get("limits", {})
                .get("amount", {})
                .get("min")
            )

            if amount <= 0:
                raise RuntimeError(
                    f"Invalid quantity for {symbol}"
                )

            if minimum is not None and amount < minimum:
                raise RuntimeError(
                    f"Quantity {amount} is below "
                    f"minimum {minimum}"
                )

            entry_order = await exchange.create_order(
                market_symbol,
                "market",
                entry_side,
                amount,
                None,
                {},
            )

            try:
                await self._create_binance_protection_orders(
                    exchange=exchange,
                    symbol=market_symbol,
                    close_side=close_side,
                    amount=amount,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )

            except Exception as protection_error:
                logger.critical(
                    "❌ SL/TP failed for %s: %s. "
                    "Emergency closing position.",
                    symbol,
                    protection_error,
                )

                try:
                    await exchange.create_order(
                        market_symbol,
                        "market",
                        close_side,
                        amount,
                        None,
                        {
                            "reduceOnly": True,
                        },
                    )
                except Exception as close_error:
                    logger.critical(
                        "❌ Emergency close failed for %s: %s",
                        symbol,
                        close_error,
                    )

                raise

            logger.info(
                "✅ Protected Binance order: "
                "%s %s amount=%s SL=%s TP=%s",
                symbol,
                direction.upper(),
                amount,
                stop_loss,
                take_profit,
            )

            return entry_order

        except ccxt.InsufficientFunds:
            logger.error(
                "❌ Insufficient funds for %s",
                symbol,
            )
            return None

        except ccxt.InvalidOrder as error:
            logger.error(
                "❌ Invalid order for %s: %s",
                symbol,
                error,
            )
            return None

        except ccxt.ExchangeError as error:
            logger.error(
                "❌ Exchange order error for %s: %s",
                symbol,
                error,
            )
            return None

        except Exception as error:
            logger.exception(
                "❌ Order failed for %s: %s",
                symbol,
                error,
            )
            return None

    async def close_position(
        self,
        symbol: str,
        direction: str,
        exchange_name: Optional[str] = None,
    ) -> bool:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )
        wanted_side = direction.lower()

        try:
            positions = await exchange.fetch_positions(
                [market_symbol]
            )

            target = None

            for position in positions:
                position_side = position.get("side")
                contracts = float(
                    position.get("contracts") or 0
                )

                if (
                    position_side == wanted_side
                    and contracts > 0
                ):
                    target = position
                    break

            if target is None:
                logger.warning(
                    "No %s position found for %s",
                    wanted_side,
                    symbol,
                )
                return False

            contracts = float(
                target.get("contracts") or 0
            )

            amount = float(
                exchange.amount_to_precision(
                    market_symbol,
                    contracts,
                )
            )

            if amount <= 0:
                return False

            close_side = (
                "sell"
                if wanted_side == "long"
                else "buy"
            )

            await exchange.create_order(
                market_symbol,
                "market",
                close_side,
                amount,
                None,
                {
                    "reduceOnly": True,
                },
            )

            return True

        except Exception as error:
            logger.exception(
                "Close position error for %s: %s",
                symbol,
                error,
            )
            return False

    async def partial_close(
        self,
        symbol: str,
        direction: str,
        percentage: int,
        exchange_name: Optional[str] = None,
    ) -> bool:
        if not 0 < percentage <= 100:
            return False

        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )
        wanted_side = direction.lower()

        try:
            positions = await exchange.fetch_positions(
                [market_symbol]
            )

            for position in positions:
                position_side = position.get("side")
                contracts = float(
                    position.get("contracts") or 0
                )

                if position_side != wanted_side:
                    continue

                if contracts <= 0:
                    continue

                amount = float(
                    exchange.amount_to_precision(
                        market_symbol,
                        contracts * percentage / 100,
                    )
                )

                if amount <= 0:
                    return False

                close_side = (
                    "sell"
                    if wanted_side == "long"
                    else "buy"
                )

                await exchange.create_order(
                    market_symbol,
                    "market",
                    close_side,
                    amount,
                    None,
                    {
                        "reduceOnly": True,
                    },
                )

                logger.info(
                    "✅ Partial close %s %s%%",
                    symbol,
                    percentage,
                )

                return True

            return False

        except Exception as error:
            logger.exception(
                "Partial close error for %s: %s",
                symbol,
                error,
            )
            return False

    async def get_open_positions(
        self,
        exchange_name: Optional[str] = None,
    ) -> List[dict]:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]

        try:
            positions = await exchange.fetch_positions()
            result = []

            for position in positions:
                contracts = float(
                    position.get("contracts") or 0
                )

                if contracts <= 0:
                    continue

                result.append(
                    {
                        "symbol": position.get(
                            "symbol",
                            "",
                        ),
                        "side": position.get(
                            "side",
                            "",
                        ),
                        "size": contracts,
                        "entry_price": float(
                            position.get(
                                "entryPrice",
                                0,
                            )
                            or 0
                        ),
                        "unrealized_pnl": float(
                            position.get(
                                "unrealizedPnl",
                                0,
                            )
                            or 0
                        ),
                        "leverage": float(
                            position.get(
                                "leverage",
                                1,
                            )
                            or 1
                        ),
                        "liquidation_price": float(
                            position.get(
                                "liquidationPrice",
                                0,
                            )
                            or 0
                        ),
                    }
                )

            return result

        except Exception as error:
            logger.error(
                "Open positions error on {}: {}",
                selected,
                error,
            )
            return []

    async def get_funding_rate(
        self,
        symbol: str,
        exchange_name: Optional[str] = None,
    ) -> float:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )

        try:
            funding = await exchange.fetch_funding_rate(
                market_symbol
            )

            return float(
                funding.get("fundingRate") or 0
            )

        except Exception as error:
            logger.debug(
                "Funding rate error {}: {}",
                symbol,
                error,
            )
            return 0.0

    async def cancel_all_orders(
        self,
        symbol: str,
        exchange_name: Optional[str] = None,
    ) -> bool:
        selected = self._resolve_exchange(
            exchange_name
        )
        exchange = self._exchanges[selected]
        market_symbol = self.normalize_symbol(
            symbol,
            selected,
        )

        try:
            await exchange.cancel_all_orders(
                market_symbol
            )
            return True

        except Exception as error:
            logger.error(
                "Cancel orders error {}: {}",
                symbol,
                error,
            )
            return False

    async def close(self) -> None:
        for exchange_name, exchange in list(
            self._exchanges.items()
        ):
            try:
                await exchange.close()
                logger.info(
                    "✅ Closed {} connection",
                    exchange_name,
                )
            except Exception as error:
                logger.error(
                    "❌ Error closing {}: {}",
                    exchange_name,
                    error,
                )

        self._exchanges.clear()
