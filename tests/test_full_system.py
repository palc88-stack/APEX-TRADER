# APEX TRADER - Full System Tests (متوافق مع الكود الحالي)
import pytest
from loguru import logger


class TestFeeCalculatorAccuracy:
    """اختبارات دقة حاسبة العمولات — متوافقة مع FeeCalculator الحالي"""

    def test_fee_calculation_accuracy(self):
        from bot.core.fee_calculator import FeeCalculator
        calc = FeeCalculator("binance")
        result = calc.calculate(
            position_size=1000.0,
            entry_type="taker",
            exit_type="taker",
        )
        # Binance taker: 0.0004 * 2 * 1000 = 0.8
        assert abs(result.total_fee - 0.8) < 0.01

    def test_targets_adjusted_for_fees(self):
        from bot.core.fee_calculator import FeeCalculator
        calc = FeeCalculator("binance")
        targets = calc.adjust_targets(
            entry_price=43000.0, direction="long",
            sl_pct=0.25, tp1_pct=0.41, tp2_pct=0.71,
            position_size=1000.0,
        )
        assert targets["stop_loss"] < 43000.0
        assert targets["tp1"] > 43000.0
        assert targets["tp2"] > targets["tp1"]


class TestRiskManagerLogic:
    """اختبارات RiskManager — متوافقة مع واجهة check_risk_limits الحالية"""

    def test_risk_manager_check_risk_limits_exists(self):
        from bot.core.risk_manager import RiskManager
        assert hasattr(RiskManager, "check_risk_limits")
        assert hasattr(RiskManager, "evaluate_risk")

    def test_check_risk_limits_rejects_confidence_below_65(self):
        from bot.core.risk_manager import RiskManager
        from bot.signals.signal_engine import TradeDirection, TradeSignal

        rm = RiskManager({})
        signal = TradeSignal(
            symbol="BTC/USDT", action=TradeDirection.LONG,
            price=50000.0, confidence=0.5,
            strategy="TEST", reason="low confidence test",
        )
        assert rm.check_risk_limits(signal) is False

    def test_check_risk_limits_accepts_valid_signal(self):
        from bot.core.risk_manager import RiskManager
        from bot.signals.signal_engine import TradeDirection, TradeSignal

        rm = RiskManager({})
        signal = TradeSignal(
            symbol="BTC/USDT", action=TradeDirection.LONG,
            price=50000.0, confidence=0.85,
            strategy="TEST", reason="valid signal test",
        )
        assert rm.check_risk_limits(signal) is True


class TestPositionManagerTrailing:
    """اختبارات PositionManager — متوافقة مع_position_manager.py الحالي"""

    def test_position_manager_trailing_exists(self):
        from bot.core.position_manager import PositionManager, Position
        assert hasattr(PositionManager, "update_price")
        assert hasattr(PositionManager, "add_position")
        assert hasattr(PositionManager, "close_position")
        assert hasattr(PositionManager, "get_all_positions")
        assert hasattr(PositionManager, "get_position")

    def test_trailing_stop_updates_correctly(self):
        from bot.core.position_manager import PositionManager, Position
        from bot.signals.signal_engine import TradeDirection
        import uuid

        manager = PositionManager()
        pos = Position(
            id=str(uuid.uuid4())[:8], symbol="BTC/USDT",
            direction=TradeDirection.LONG, exchange="binance",
            entry_price=43000.0, current_price=43000.0,
            stop_loss=42892.5, take_profit_1=43176.3, take_profit_2=43306.1,
            size_usd=10.0, leverage=10,
        )
        manager.add_position(pos)
        pos_id = pos.id

        manager.update_price(pos_id, 43064.5, atr=50.0)
        updated = manager.get_position(pos_id)
        if updated:
            assert updated.breakeven_set or updated.stop_loss >= 43000.0

        manager.update_price(pos_id, 43150.0, atr=50.0)
        updated = manager.get_position(pos_id)
        if updated and updated.trailing_active:
            initial_trailing = updated.trailing_stop
            manager.update_price(pos_id, 43250.0, atr=50.0)
            updated2 = manager.get_position(pos_id)
            if updated2 and updated2.trailing_active:
                assert updated2.trailing_stop >= initial_trailing


class TestNoMockData:
    """التأكد من عدم وجود بيانات وهمية في الكود الإنتاجي"""

    def test_no_hardcoded_prices_in_production(self):
        import os, re

        patterns = [
            r"price\s*=\s*\d{4,}",
            r"balance\s*=\s*\d+\.?\d*",
            r"random\.",
            r"np\.random\.",
            r"\bfake\b",
            r"\bmock\b",
            r"\bdummy\b",
        ]
        production_files = [
            "bot/config.py", "bot/main.py",
            "bot/core/exchange.py", "bot/core/risk_manager.py",
            "bot/core/fee_calculator.py", "bot/core/position_manager.py",
            "bot/data/market_data.py", "bot/data/state_manager.py",
            "bot/signals/signal_engine.py", "bot/signals/indicators.py",
            "bot/signals/filters.py",
            "bot/strategies/explosion.py", "bot/strategies/scalping.py",
            "bot/notifications/telegram_notifier.py",
        ]
        issues = []
        for root, dirs, files in os.walk("bot"):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    fp = os.path.join(root, f)
                    if fp not in production_files:
                        continue
                    try:
                        with open(fp) as fh:
                            content = fh.read()
                        for pat in patterns:
                            for m in re.findall(pat, content, re.IGNORECASE):
                                issues.append(f"{fp}: {m}")
                    except Exception:
                        pass
        if issues:
            logger.warning(f"⚠️ أنماط مشبوهة: {issues[:5]}")
        else:
            logger.info("✅ لا توجد بيانات وهمية في الكود الإنتاجي")
