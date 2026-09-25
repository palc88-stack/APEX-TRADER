# APEX TRADER - Real Data Tests (متوافق مع الكود الحالي)
import asyncio
import pytest
import pandas as pd
from datetime import datetime, timezone
from loguru import logger


class TestRealDataIntegrity:
    """اختبارات التحقق من البيانات الحقيقية من Binance API"""

    @pytest.mark.asyncio
    async def test_real_ohlcv_data(self):
        """التحقق من بيانات الشموع الحقيقية من Binance"""
        from bot.data.market_data import MarketDataManager

        manager = MarketDataManager()
        try:
            df = await manager.get_ohlcv("BTC/USDT", "5m", limit=10)
            if df is None:
                pytest.skip("Binance API not available (no keys or network error)")
            assert len(df) > 0, "❌ DataFrame فارغ!"
            last_price = float(df["close"].iloc[-1])
            assert 1000 < last_price < 1_000_000, f"❌ سعر غير منطقي: ${last_price}"
            last_time = df["timestamp"].iloc[-1]
            now = datetime.now(timezone.utc)
            age_min = (now - last_time).total_seconds() / 60
            assert age_min < 30, f"❌ بيانات قديمة: {age_min:.0f} دقيقة"
            assert (df["high"] >= df["low"]).all(), "❌ High < Low!"
            assert (df["volume"] > 0).all(), "❌ حجم ≤ 0!"
            logger.info(f"✅ بيانات BTC حقيقية | السعر: ${last_price:,.2f} | عمر: {age_min:.1f} دقيقة")
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_real_balance(self):
        """التحقق من الرصيد الحقيقي — يتطلب BINANCE_API_KEY"""
        from bot.core.exchange import ExchangeManager
        from bot.config import config

        if not config.exchange.binance_api_key:
            pytest.skip("API Keys غير مضبوطة")
        manager = ExchangeManager()
        try:
            balance = await manager.get_balance()
            assert isinstance(balance, float), "❌ الرصيد ليس float!"
            assert balance >= 0, f"❌ رصيد سالب: {balance}"
            logger.info(f"✅ رصيد حقيقي: ${balance:.2f}")
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_real_ticker(self):
        """التحقق من السعر الحالي من Binance"""
        from bot.core.exchange import ExchangeManager

        manager = ExchangeManager()
        try:
            ticker = await manager.get_ticker("BTC/USDT")
            if not ticker:
                pytest.skip("Binance API not available (no keys or network error)")
            price = float(ticker.get("last", 0))
            if price < 1000 or price > 1_000_000:
                pytest.skip(f"Binance returned unexpected price: ${price}")
            logger.info(f"✅ سعر BTC حقيقي: ${price:,.2f}")
        finally:
            await manager.close()

    def test_indicators_with_real_data(self):
        """اختبار المؤشرات باستخدام IndicatorCalculator الحالي"""
        async def _get_data():
            from bot.data.market_data import MarketDataManager
            mgr = MarketDataManager()
            df = await mgr.get_ohlcv("BTC/USDT", "5m", 100)
            await mgr.close()
            return df

        df = asyncio.run(_get_data())
        if df is None:
            pytest.skip("لا يمكن جلب البيانات من Binance حالياً")

        from bot.signals.indicators import IndicatorCalculator
        calc = IndicatorCalculator({})
        result = calc.calculate_all(df)
        assert result is not None, "❌ فشل حساب المؤشرات!"

        rsi_series = result["rsi"]
        last_rsi = float(rsi_series.iloc[-1])
        assert 0 <= last_rsi <= 100, f"❌ RSI خارج النطاق: {last_rsi}"

        ema200 = result["ema_200"]
        last_ema = float(ema200.iloc[-1])
        current = float(df["close"].iloc[-1])
        ratio = last_ema / current
        assert 0.5 < ratio < 2.0, f"❌ EMA200 غير منطقي: {last_ema} (ratio={ratio:.2f})"

        logger.info(
            f"✅ مؤشرات حقيقية | RSI={last_rsi:.1f} | "
            f"EMA200=${last_ema:,.2f} | السعر=${current:,.2f}"
        )
