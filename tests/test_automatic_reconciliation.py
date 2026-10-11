from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.main import ApexTraderBot


class FakeStateManager:
    def __init__(self, trade, close_orders=None):
        self.trades = [dict(trade)]
        self.close_orders = list(close_orders or [])
        self.recorded_orders = []
        self.updated_orders = []
        self.saved_trades = []
        self.flat = []
        self.closed = []
        self.released = []

    def get_open_trades_from_db(self):
        return [dict(trade) for trade in self.trades]

    def get_reconciliation_close_orders(self, trade_id):
        return [dict(order) for order in self.close_orders]

    def record_trade_order(self, payload):
        order = {"id": len(self.recorded_orders) + 1, **payload}
        self.recorded_orders.append(order)
        self.close_orders.insert(0, order)
        return order["id"]

    def update_trade_order(self, order_id, updates):
        self.updated_orders.append((order_id, dict(updates)))
        return True

    def save_trade_state(self, trade):
        self.saved_trades.append(dict(trade))
        self.trades = [dict(trade)]
        return True

    def mark_reconciliation_flat(self, trade, note):
        self.flat.append((dict(trade), note))
        self.trades = []
        return True

    def mark_reconciliation_closed(self, trade, **kwargs):
        self.closed.append((dict(trade), kwargs))
        self.trades = []
        return True

    def record_trade_fill(self, payload):
        return True

    def release_position_slot(self, **kwargs):
        self.released.append(kwargs)
        return True


class FakeExchange:
    is_testnet = True

    def __init__(self, positions=None, pending_order=None):
        self.positions = list(positions or [])
        self.pending_order = pending_order
        self.close_calls = []
        self.cancelled_protections = []

    async def get_all_open_positions_result(self):
        return SimpleNamespace(ok=True, data=list(self.positions), error=None)

    async def fetch_order_for_reconciliation(self, symbol, *, order_id=None, client_order_id=None):
        return self.pending_order

    async def has_open_reduce_only_market_order(self, symbol):
        return False

    async def reduce_only_close(self, **kwargs):
        self.close_calls.append(dict(kwargs))
        return {"id": "testnet-order-1", "status": "closed", "clientOrderId": kwargs["client_order_id"]}

    async def fetch_fill_details(self, order_id, symbol):
        return None

    async def cancel_protection_orders(self, symbol):
        self.cancelled_protections.append(symbol)


class FakeTelegram:
    async def send_reconciliation_closed(self, **kwargs):
        return True


TRADE = {
    "id": "trade-1",
    "entry_order_id": "entry-1",
    "symbol": "BTC/USDT:USDT",
    "direction": "LONG",
    "entry_quantity": 2.0,
    "remaining_quantity": 2.0,
    "status": "NEEDS_RECONCILIATION",
}


def make_bot(*, trade=None, positions=None, close_orders=None, pending_order=None):
    bot = object.__new__(ApexTraderBot)
    bot.config = SimpleNamespace(
        environment="testnet",
        auto_reconcile_close_enabled=True,
        trading_execution_enabled=True,
        exchange=SimpleNamespace(primary_exchange=lambda: "binance"),
    )
    bot.state_manager = FakeStateManager(trade or TRADE, close_orders=close_orders)
    bot.exchange = FakeExchange(positions=positions, pending_order=pending_order)
    bot.telegram = FakeTelegram()
    bot._reconciliation_blocked_symbols = {TRADE["symbol"]}
    return bot


@pytest.mark.asyncio
async def test_flat_testnet_position_resolves_without_fabricating_fill_or_pnl():
    bot = make_bot(positions=[])

    await bot._auto_close_reconciliation_positions()

    assert len(bot.state_manager.flat) == 1
    assert bot.exchange.close_calls == []
    assert bot.state_manager.released
    assert bot.exchange.cancelled_protections == [TRADE["symbol"]]


@pytest.mark.asyncio
async def test_pending_close_intent_is_checked_not_duplicated():
    prior = {
        "id": 9,
        "status": "submitted",
        "exchange_order_id": "pending-1",
        "client_order_id": "apex-r-existing",
        "submitted_at": "2026-10-11T00:00:00+00:00",
    }
    bot = make_bot(
        positions=[{"symbol": TRADE["symbol"], "side": "long", "contracts": 2.0}],
        close_orders=[prior],
    )
    bot.exchange.pending_order = {"id": "pending-1", "status": "open"}

    await bot._auto_close_reconciliation_positions()

    assert bot.exchange.close_calls == []
    assert bot.state_manager.updated_orders


@pytest.mark.asyncio
async def test_auto_close_persists_intent_and_caps_request_to_live_testnet_quantity():
    bot = make_bot(
        positions=[{"symbol": TRADE["symbol"], "side": "long", "contracts": 2.0}],
    )

    await bot._auto_close_reconciliation_positions()

    assert len(bot.state_manager.recorded_orders) == 1
    intent = bot.state_manager.recorded_orders[0]
    assert intent["reduce_only"] is True
    assert intent["requested_quantity"] == 2.0
    assert intent["client_order_id"]
    assert bot.exchange.close_calls[0]["amount"] == 2.0
    assert bot.exchange.close_calls[0]["client_order_id"] == intent["client_order_id"]
    assert bot.state_manager.flat == []
    assert bot.state_manager.closed == []


@pytest.mark.asyncio
async def test_live_environment_never_uses_automatic_reconciliation_close():
    bot = make_bot(
        positions=[{"symbol": TRADE["symbol"], "side": "long", "contracts": 2.0}],
    )
    bot.config.environment = "live"

    await bot._auto_close_reconciliation_positions()

    assert bot.exchange.close_calls == []
    assert bot.state_manager.recorded_orders == []
    assert bot.state_manager.flat == []


from bot.data.state_manager import StateManager


def _fill_stub():
    source = SimpleNamespace(value="exchange_fill")
    return SimpleNamespace(
        price=105.0,
        quantity=1.5,
        fee=0.15,
        fee_currency="USDT",
        filled_at="2026-10-11T00:00:00+00:00",
        slippage_bps=0.0,
        mark_price=None,
        trigger_price=None,
        price_source=source,
        quantity_source=source,
        fee_source=source,
    )


def test_reconciliation_pnl_aggregates_confirmed_exit_fills_and_entry_fee():
    manager = object.__new__(StateManager)
    rows = [
        {"quantity": 0.5, "price": 110.0, "fee_amount": 0.05,
         "price_source": "exchange_fill", "quantity_source": "exchange_fill", "fee_source": "exchange_fill"},
        {"quantity": 1.5, "price": 105.0, "fee_amount": 0.15,
         "price_source": "exchange_fill", "quantity_source": "exchange_fill", "fee_source": "exchange_fill"},
    ]
    manager.get_confirmed_exit_fills = lambda trade_id, exit_side: rows
    saved = {}
    manager.save_trade_state = lambda trade: saved.update(trade) or True
    trade = {
        "id": "trade-1",
        "symbol": "BTC/USDT:USDT",
        "direction": "LONG",
        "entry_price": 100.0,
        "entry_quantity": 2.0,
        "entry_fee": 0.2,
        "entry_price_source": "exchange_fill",
        "entry_quantity_source": "exchange_fill",
        "entry_fee_source": "exchange_fill",
        "margin_usd": 100.0,
        "account_balance_at_entry": 1000.0,
    }

    result = manager.mark_reconciliation_closed(
        trade, order_id="close-2", fill=_fill_stub(), close_reason="auto_reconciliation_reduce_only"
    )

    assert result is True
    assert saved["status"] == "CLOSED"
    assert saved["exit_quantity"] == pytest.approx(2.0)
    assert saved["exit_price"] == pytest.approx(106.25)
    assert saved["pnl"] == pytest.approx(12.1)
    assert saved["pnl_source"] == "exchange_fill"


def test_reconciliation_pnl_refuses_incomplete_exit_fill_coverage():
    manager = object.__new__(StateManager)
    manager.get_confirmed_exit_fills = lambda trade_id, exit_side: [
        {"quantity": 1.9, "price": 105.0, "fee_amount": 0.15,
         "price_source": "exchange_fill", "quantity_source": "exchange_fill", "fee_source": "exchange_fill"},
    ]
    manager.save_trade_state = lambda trade: pytest.fail("incomplete fills must not close as confirmed")
    trade = {
        "id": "trade-1",
        "direction": "LONG",
        "entry_price": 100.0,
        "entry_quantity": 2.0,
        "entry_fee": 0.2,
        "entry_price_source": "exchange_fill",
        "entry_quantity_source": "exchange_fill",
        "entry_fee_source": "exchange_fill",
    }

    result = manager.mark_reconciliation_closed(
        trade, order_id="close-2", fill=_fill_stub(), close_reason="auto_reconciliation_reduce_only"
    )

    assert result is False
