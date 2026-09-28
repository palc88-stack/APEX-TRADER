import asyncio

from bot.core.exchange import ExchangeManager


class FakeExchange:
    markets = {
        symbol: {
            "active": True,
            "swap": True,
            "linear": True,
            "quote": "USDT",
            "symbol": symbol,
        }
        for symbol in (
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
            "XRP/USDT:USDT",
        )
    }

    async def fetch_tickers(self):
        return {
            "BTC/USDT:USDT": {"quoteVolume": 30_000_000},
            "ETH/USDT:USDT": {"quoteVolume": 20_000_000},
            "SOL/USDT:USDT": {"quoteVolume": 10_000_000},
            "XRP/USDT:USDT": {"quoteVolume": 1_000_000},
        }


def test_volume_scanner_caps_final_symbol_list_at_limit():
    manager = object.__new__(ExchangeManager)
    manager._exchange = FakeExchange()
    manager._markets_loaded = True

    result = asyncio.run(
        manager.get_top_usdt_perpetual_symbols(
            limit=3,
            min_quote_volume_usdt=5_000_000,
            base_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"],
        )
    )

    assert result == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    assert len(result) <= 3
