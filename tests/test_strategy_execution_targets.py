import pandas as pd

from bot.signals.indicators import IndicatorCalculator
from bot.data.state_manager import StateManager
from bot.strategies.router import StrategyRouter


class _PassFilters:
    def validate_signal(self, action, latest, df=None):
        return True


class _NoExplosion:
    def detect(self, df, symbol):
        return None


class _Scalping:
    max_stop_loss_pct = 0.003
    target_profit_pct = 0.005

    def evaluate_scalp_setup(self, df, symbol):
        return {
            "action": "BUY",
            "stop_loss_pct": 0.002,
            "take_profit_pct": 0.007,
            "reason": "test scalp",
        }


class _InsertResult:
    data = [{"id": 41}]


class _OrdersTable:
    def __init__(self):
        self.inserted = None

    def insert(self, payload):
        self.inserted = payload
        return self

    def execute(self):
        return _InsertResult()


class _LedgerClient:
    def __init__(self):
        self.orders = _OrdersTable()

    def table(self, name):
        assert name == "trade_orders"
        return self.orders


def test_ema200_requires_full_warmup_window():
    frame = pd.DataFrame({"close": [float(i) for i in range(1, 201)]})
    ema = IndicatorCalculator.calculate_ema(frame, period=200)

    assert ema.iloc[:199].isna().all()
    assert pd.notna(ema.iloc[199])


def test_scalping_targets_are_carried_by_router_decision():
    frame = pd.DataFrame({
        "close": [101.0],
        "ema_200": [100.0],
        "rsi": [50.0],
        "volume": [1000.0],
    })
    router = StrategyRouter("SCALPING", _PassFilters(), _NoExplosion(), _Scalping())

    result = router.evaluate(frame, "BTC/USDT")

    assert result["strategy"] == "SCALPING"
    assert result["stop_loss_pct"] == 0.002
    assert result["take_profit_pct"] == 0.007


def test_trade_order_status_is_normalized_for_sql_ledger():
    manager = StateManager.__new__(StateManager)
    manager.client = _LedgerClient()

    order_id = manager.record_trade_order({
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "side": "buy",
        "order_type": "market",
        "status": "closed",
    })

    assert order_id == 41
    assert manager.client.orders.inserted["status"] == "filled"
