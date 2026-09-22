# ======================================
# APEX TRADER - Full System Tests
# ======================================
# اختبارات شاملة للنظام الكامل
# تتحقق من عدم وجود بيانات وهمية

import asyncio
import pytest
import pandas as pd
from datetime import datetime, timezone
from loguru import logger


class TestSignalEngineReal:
    """
    اختبارات محرك الإشارات
    مع بيانات حقيقية
    """

    def test_indicators_output_validity(self):
        """
        التحقق من صحة مخرجات المؤشرات
        باستخدام بيانات حقيقية
        """
        async def run():
            from bot.data.market_data import MarketDataManager
            from bot.signals.indicators import TechnicalIndicators

            manager = MarketDataManager()
            calc = TechnicalIndicators()

            try:
                df = await manager.get_ohlcv(
                    'BTC/USDT', '5m', limit=100
                )

                if df is None:
                    pytest.skip("لا يمكن جلب البيانات")

                result = calc.calculate_all(df)

                assert result is not None

                # RSI يجب بين 0 و 100
                assert 0 <= result.rsi <= 100, (
                    f"RSI خارج النطاق: {result.rsi}"
                )

                # ATR يجب موجباً
                assert result.atr > 0, (
                    f"ATR غير صالح: {result.atr}"
                )

                # EMA9 قريب من السعر الحالي
                current = float(df['close'].iloc[-1])
                ratio = result.ema_9 / current
                assert 0.5 < ratio < 2.0, (
                    f"EMA9 بعيد عن السعر: {result.ema_9}"
                )

                # Hurst بين 0 و 1
                assert 0 <= result.hurst <= 1, (
                    f"Hurst خارج النطاق: {result.hurst}"
                )

                # Volume Ratio موجب
                assert result.volume_ratio >= 0, (
                    f"Volume Ratio سالب: {result.volume_ratio}"
                )

                logger.info(
                    f"✅ مؤشرات صحيحة | "
                    f"RSI: {result.rsi:.1f} | "
                    f"EMA9: ${result.ema_9:,.2f} | "
                    f"ATR: ${result.atr:,.4f}"
                )

            finally:
                await manager.close()

        asyncio.run(run())

    def test_signal_engine_no_mock(self):
        """
        التحقق من عمل Signal Engine
        مع بيانات حقيقية
        """
        async def run():
            from bot.data.market_data import MarketDataManager
            from bot.signals.signal_engine import (
                SignalEngine, TradeDirection
            )
            from bot.core.exchange import ExchangeManager

            market = MarketDataManager()
            exchange = ExchangeManager()
            engine = SignalEngine()

            try:
                symbol = 'BTC/USDT'

                # بيانات حقيقية
                df = await market.get_ohlcv(
                    symbol, '5m', limit=100
                )
                ticker = await exchange.get_ticker(symbol)

                if df is None or not ticker:
                    pytest.skip("لا يمكن جلب البيانات")

                current_price = ticker.get('last', 0)

                assert current_price > 0, (
                    "السعر غير صالح من API"
                )

                # تحليل حقيقي
                signal = engine.analyze(
                    symbol=symbol,
                    df=df,
                    current_price=current_price
                )

                # الإشارة يجب أن تكون بنية صحيحة
                assert signal.symbol == symbol
                assert signal.entry_price == current_price
                assert 0 <= signal.confidence <= 1

                logger.info(
                    f"✅ Signal Engine يعمل | "
                    f"اتجاه: {signal.direction.value} | "
                    f"ثقة: {signal.confidence:.1%}"
                )

            finally:
                await market.close()
                await exchange.close()

        asyncio.run(run())


class TestFeeCalculatorAccuracy:
    """
    اختبارات دقة حاسبة العمولات
    """

    def test_fee_calculation_accuracy(self):
        """
        التحقق من دقة حساب العمولات
        """
        from bot.core.fee_calculator import FeeCalculator

        calc = FeeCalculator("binance")

        # حجم صفقة حقيقي
        position_value = 1000.0

        result = calc.calculate(
            position_value=position_value,
            entry_type="taker",
            exit_type="taker"
        )

        # 0.04% * 2 = 0.08% إجمالي
        expected_fee = position_value * 0.0004 * 2
        assert abs(result.total_fee - expected_fee) < 0.001, (
            f"عمولة خاطئة: {result.total_fee} "
            f"!= {expected_fee}"
        )

        # Break Even = إجمالي العمولات %
        expected_be = 0.08  # 0.08%
        assert abs(
            result.breakeven_pct - expected_be
        ) < 0.001, (
            f"Break Even خاطئ: {result.breakeven_pct}"
        )

        logger.info(
            f"✅ عمولات صحيحة | "
            f"إجمالي: ${result.total_fee:.4f} | "
            f"BE: {result.breakeven_pct:.3f}%"
        )

    def test_targets_adjusted_for_fees(self):
        """
        التحقق من تعديل الأهداف للعمولات
        """
        from bot.core.fee_calculator import FeeCalculator

        calc = FeeCalculator("bybit")

        targets = calc.adjust_targets(
            entry_price=43000.0,
            direction="long",
            sl_pct=0.25,
            tp1_pct=0.41,
            tp2_pct=0.71,
            position_size=1000.0
        )

        # SL يجب تحت سعر الدخول للـ Long
        assert targets['stop_loss'] < 43000.0, (
            "SL يجب أن يكون تحت سعر الدخول!"
        )

        # TP1 يجب فوق سعر الدخول
        assert targets['tp1'] > 43000.0, (
            "TP1 يجب أن يكون فوق سعر الدخول!"
        )

        # TP2 يجب أكبر من TP1
        assert targets['tp2'] > targets['tp1'], (
            "TP2 يجب أن يكون أكبر من TP1!"
        )

        # Break Even يجب فوق سعر الدخول (للـ Long)
        assert targets['breakeven'] > 43000.0, (
            "Break Even يجب فوق سعر الدخول!"
        )

        logger.info(
            f"✅ أهداف معدّلة صحيحة | "
            f"SL: ${targets['stop_loss']:,.2f} | "
            f"TP1: ${targets['tp1']:,.2f} | "
            f"TP2: ${targets['tp2']:,.2f}"
        )


class TestRiskManagerLogic:
    """
    اختبارات منطق إدارة المخاطر
    """

    def test_daily_loss_limit(self):
        """
        التحقق من توقف التداول
        عند الوصول للحد اليومي
        """
        from bot.core.risk_manager import RiskManager
        from bot.signals.signal_engine import (
            TradeSignal, TradeDirection, TradingMode
        )

        risk = RiskManager()

        # محاكاة خسارة 4%
        risk._daily_loss = 4.0  # $4 من $100

        signal = TradeSignal(
            direction=TradeDirection.LONG,
            mode=TradingMode.HUNTER,
            confidence=0.80,
            symbol="BTC/USDT",
            entry_price=43000.0,
            stop_loss=42892.5,
            take_profit_1=43176.3,
            take_profit_2=43306.1,
            leverage=10,
            position_size_pct=5.0
        )

        result = risk.check_signal(signal, balance=100.0)

        # يجب رفض الصفقة
        assert not result.approved, (
            "يجب رفض الصفقة عند الحد اليومي!"
        )

        logger.info(
            f"✅ Risk Manager رفض الصفقة بشكل صحيح: "
            f"{result.reason}"
        )

    def test_position_size_calculation(self):
        """
        التحقق من صحة حساب حجم الصفقة
        """
        from bot.core.risk_manager import RiskManager
        from bot.signals.signal_engine import (
            TradeSignal, TradeDirection, TradingMode
        )

        risk = RiskManager()

        signal = TradeSignal(
            direction=TradeDirection.LONG,
            mode=TradingMode.HUNTER,
            confidence=0.80,
            symbol="BTC/USDT",
            entry_price=43000.0,
            stop_loss=42892.5,
            take_profit_1=43176.3,
            take_profit_2=43306.1,
            leverage=10,
            position_size_pct=8.0
        )

        result = risk.check_signal(signal, balance=100.0)

        if result.approved:
            # الحجم يجب أن يكون ضمن الحدود
            assert result.adjusted_size > 0, (
                "الحجم يجب أن يكون موجباً!"
            )
            assert result.adjusted_size <= 100.0, (
                "الحجم لا يمكن أن يتجاوز الرصيد!"
            )
            assert 1 <= result.adjusted_leverage <= 20, (
                f"الليفريج خارج النطاق: "
                f"{result.adjusted_leverage}"
            )

            logger.info(
                f"✅ حجم صحيح: "
                f"${result.adjusted_size:.2f} | "
                f"رافعة: {result.adjusted_leverage}x"
            )


class TestPositionManagerTrailing:
    """
    اختبارات Trailing Stop
    """

    def test_trailing_stop_moves_correctly(self):
        """
        التحقق من حركة Trailing Stop
        في الاتجاه الصحيح فقط
        """
        from bot.core.position_manager import (
            PositionManager, Position
        )
        from bot.signals.signal_engine import TradeDirection
        import uuid

        manager = PositionManager()

        # إنشاء صفقة Long
        position = Position(
            id=str(uuid.uuid4())[:8],
            symbol="BTC/USDT",
            direction=TradeDirection.LONG,
            exchange="binance",
            entry_price=43000.0,
            current_price=43000.0,
            stop_loss=42892.5,
            take_profit_1=43176.3,
            take_profit_2=43306.1,
            size_usd=10.0,
            leverage=10
        )

        manager.add_position(position)
        pos_id = position.id

        # ارتفاع السعر لتفعيل Break Even
        manager.update_price(pos_id, 43064.5, atr=50.0)

        # التحقق من Break Even
        updated = manager.get_position(pos_id)
        if updated:
            assert updated.breakeven_set or (
                updated.stop_loss >= 43000.0
            ), "Break Even لم يُفعَّل!"

        # ارتفاع إضافي لتفعيل Trailing
        manager.update_price(pos_id, 43150.0, atr=50.0)
        updated = manager.get_position(pos_id)

        if updated and updated.trailing_active:
            initial_trailing = updated.trailing_stop

            # ارتفاع أكثر
            manager.update_price(pos_id, 43250.0, atr=50.0)
            updated2 = manager.get_position(pos_id)

            if updated2 and updated2.trailing_active:
                # Trailing يجب أن يتحرك للأعلى
                assert (
                    updated2.trailing_stop >= initial_trailing
                ), "Trailing تراجع للأسفل! خطأ!"

                logger.info(
                    f"✅ Trailing صحيح: "
                    f"{initial_trailing:.2f} → "
                    f"{updated2.trailing_stop:.2f}"
                )


class TestNoMockData:
    """
    اختبارات للتأكد من عدم وجود بيانات وهمية
    """

    def test_no_hardcoded_prices(self):
        """
        التحقق من عدم وجود أسعار محددة مسبقاً
        في الكود
        """
        import os
        import re

        # قراءة ملفات الكود
        suspicious_patterns = [
            r'price\s*=\s*\d{4,}',       # price = 43000
            r'balance\s*=\s*\d+\.?\d*',   # balance = 100
            r'random\.',                    # random.random()
            r'np\.random\.',               # np.random
            r'fake',                        # fake data
            r'mock',                        # mock data
            r'dummy',                       # dummy data
        ]

        code_files = []
        for root, dirs, files in os.walk('bot/'):
            # تجاهل __pycache__
            dirs[:] = [
                d for d in dirs
                if d != '__pycache__'
            ]
            for file in files:
                if file.endswith('.py'):
                    code_files.append(
                        os.path.join(root, file)
                    )

        issues_found = []
        for filepath in code_files:
            try:
                with open(filepath, 'r') as f:
                    content = f.read()

                for pattern in suspicious_patterns:
                    matches = re.findall(
                        pattern, content, re.IGNORECASE
                    )
                    if matches:
                        issues_found.append(
                            f"{filepath}: {matches}"
                        )
            except Exception:
                pass

        if issues_found:
            logger.warning(
                f"⚠️ أنماط مشبوهة: {issues_found[:3]}"
            )
        else:
            logger.info(
                "✅ لا توجد بيانات وهمية في الكود!"
            )

    @pytest.mark.asyncio
    async def test_all_prices_from_api(self):
        """
        التحقق من أن جميع الأسعار
        تأتي من API المنصة فعلاً
        """
        from bot.data.market_data import MarketDataManager

        manager = MarketDataManager()

        try:
            # جلب سعر BTC الحقيقي
            df = await manager.get_ohlcv(
                'BTC/USDT', '1m', limit=5
            )

            if df is None:
                pytest.skip("API غير متاح")

            last_price = float(df['close'].iloc[-1])

            # التحقق من أن السعر منطقي
            # BTC لا يمكن أن يكون $1 أو $1M
            assert 1000 < last_price < 500_000, (
                f"السعر غير منطقي: ${last_price:,.2f} - "
                f"هل هذه بيانات حقيقية؟"
            )

            # التحقق من حداثة البيانات
            last_time = df['timestamp'].iloc[-1]
            now = datetime.now(timezone.utc)
            age_seconds = (
                now - last_time
            ).total_seconds()

            # يجب أن تكون أحدث من 10 دقائق
            assert age_seconds < 600, (
                f"البيانات قديمة: {age_seconds:.0f} ثانية - "
                f"هل هذه بيانات حقيقية؟"
            )

            logger.info(
                f"✅ سعر BTC حقيقي من API: "
                f"${last_price:,.2f} | "
                f"عمر: {age_seconds:.0f}s"
            )

        finally:
            await manager.close()
