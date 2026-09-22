# ======================================
# APEX TRADER - Real Data Tests
# ======================================
# اختبارات تتحقق من البيانات الحقيقية
# لا Mock ولا بيانات وهمية!

import asyncio
import pytest
import pandas as pd
from loguru import logger


class TestRealDataIntegrity:
    """
    اختبارات التحقق من البيانات الحقيقية
    
    تتحقق من أن:
    - البيانات حقيقية من API
    - لا قيم وهمية أو محاكاة
    - الأسعار منطقية
    - البيانات حديثة
    """
    
    @pytest.mark.asyncio
    async def test_real_ohlcv_data(self):
        """التحقق من بيانات الشموع الحقيقية"""
        from bot.data.market_data import MarketDataManager
        
        manager = MarketDataManager()
        
        try:
            df = await manager.get_ohlcv(
                'BTC/USDT', '5m', limit=10
            )
            
            # يجب أن تكون بيانات حقيقية
            assert df is not None, "❌ لا بيانات!"
            assert len(df) > 0, "❌ DataFrame فارغ!"
            
            # الأسعار يجب أن تكون منطقية
            last_price = df['close'].iloc[-1]
            assert last_price > 1000, (
                f"❌ سعر BTC غير منطقي: ${last_price}"
            )
            assert last_price < 1_000_000, (
                f"❌ سعر BTC مبالغ فيه: ${last_price}"
            )
            
            # البيانات يجب أن تكون حديثة
            last_time = df['timestamp'].iloc[-1]
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            age_minutes = (
                now - last_time
            ).total_seconds() / 60
            
            assert age_minutes < 30, (
                f"❌ بيانات قديمة: {age_minutes:.0f} دقيقة"
            )
            
            # High >= Low دائماً
            assert (df['high'] >= df['low']).all(), (
                "❌ High أقل من Low!"
            )
            
            # الحجم يجب أن يكون موجباً
            assert (df['volume'] > 0).all(), (
                "❌ حجم سالب أو صفر!"
            )
            
            logger.info(
                f"✅ بيانات BTC حقيقية | "
                f"آخر سعر: ${last_price:,.2f} | "
                f"عمر: {age_minutes:.1f} دقيقة"
            )
            
        finally:
            await manager.close()
    
    @pytest.mark.asyncio
    async def test_real_balance(self):
        """
        التحقق من الرصيد الحقيقي
        ملاحظة: يحتاج مفاتيح API صالحة
        """
        from bot.core.exchange import ExchangeManager
        from bot.config import config
        
        # تخطي إذا لم تكن API Keys مضبوطة
        if not config.exchange.binance_api_key:
            pytest.skip("API Keys غير مضبوطة")
        
        manager = ExchangeManager()
        
        try:
            balance = await manager.get_balance()
            
            # الرصيد يجب أن يكون رقماً
            assert isinstance(balance, float), (
                "❌ الرصيد ليس رقماً!"
            )
            assert balance >= 0, (
                f"❌ رصيد سالب: {balance}"
            )
            
            logger.info(f"✅ رصيد حقيقي: ${balance:.2f}")
            
        finally:
            await manager.close()
    
    @pytest.mark.asyncio
    async def test_real_ticker(self):
        """التحقق من السعر الحقيقي"""
        from bot.core.exchange import ExchangeManager
        
        manager = ExchangeManager()
        
        try:
            ticker = await manager.get_ticker('BTC/USDT')
            
            assert ticker, "❌ لا بيانات ticker!"
            
            price = ticker.get('last', 0)
            
            # سعر BTC يجب أن يكون منطقياً
            assert 1000 < price < 1_000_000, (
                f"❌ سعر غير منطقي: ${price}"
            )
            
            logger.info(f"✅ سعر BTC حقيقي: ${price:,.2f}")
            
        finally:
            await manager.close()
    
    def test_indicators_with_real_data(self):
        """
        اختبار المؤشرات مع بيانات حقيقية
        يُشغَّل بعد جلب البيانات
        """
        # جلب بيانات حقيقية أولاً
        async def get_data():
            from bot.data.market_data import MarketDataManager
            manager = MarketDataManager()
            df = await manager.get_ohlcv('BTC/USDT', '5m', 100)
            await manager.close()
            return df
        
        df = asyncio.run(get_data())
        
        if df is None:
            pytest.skip("لا يمكن جلب البيانات الآن")
        
        from bot.signals.indicators import TechnicalIndicators
        
        calc = TechnicalIndicators()
        result = calc.calculate_all(df)
        
        assert result is not None, "❌ فشل حساب المؤشرات!"
        
        # EMA يجب أن يكون قريباً من السعر الحالي
        current_price = df['close'].iloc[-1]
        
        assert 0.5 < (result.ema_9 / current_price) < 2.0, (
            f"❌ EMA غير منطقي: {result.ema_9}"
        )
        
        # RSI بين 0 و 100
        assert 0 <= result.rsi <= 100, (
            f"❌ RSI غير صالح: {result.rsi}"
        )
        
        # ATR يجب أن يكون موجباً
        assert result.atr > 0, (
            f"❌ ATR غير صالح: {result.atr}"
        )
        
        logger.info(
            f"✅ مؤشرات حقيقية | "
            f"EMA9: ${result.ema_9:,.2f} | "
            f"RSI: {result.rsi:.1f} | "
            f"ATR: ${result.atr:,.2f}"
        )
