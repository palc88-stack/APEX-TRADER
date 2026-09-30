from scripts.verify_testnet_consistency import compare_positions, validate_pnl, validate_slots


def test_matching_position_has_no_findings():
    trades = [{
        "id": "t-1",
        "symbol": "FXS/USDT:USDT",
        "status": "OPEN",
        "entry_quantity": 2.0,
        "remaining_quantity": 2.0,
    }]
    positions = [{
        "symbol": "FXS/USDT:USDT",
        "contracts": 2.001,
        "info": {"positionAmt": "2.001"},
    }]
    assert compare_positions(trades, positions) == []


def test_position_mismatch_is_reported():
    trades = [{
        "id": "t-1",
        "symbol": "BTC/USDT",
        "status": "OPEN",
        "entry_quantity": 1.0,
        "remaining_quantity": 1.0,
    }]
    positions = [{"symbol": "BTC/USDT:USDT", "contracts": 1.02}]
    findings = compare_positions(trades, positions)
    assert findings[0]["type"] == "quantity_mismatch"


def test_orphan_exchange_position_is_reported():
    findings = compare_positions([], [{"symbol": "ETH/USDT:USDT", "contracts": 0.5}])
    assert findings[0]["type"] == "exchange_position_without_db_trade"


def test_occupied_slot_without_trade_is_reported():
    snapshot = {
        "trades": [],
        "slots": [{"slot_no": 1, "status": "occupied", "trade_id": "missing", "symbol": "BTC/USDT"}],
    }
    assert validate_slots(snapshot)[0]["type"] == "occupied_slot_without_open_trade"


def test_pnl_validation_compares_state_to_confirmed_summary():
    matching = {
        "bot_state": {"daily_realized_pnl": -2.5, "daily_loss_used_usd": 2.5},
        "daily_summary": {"confirmed_realized_pnl": -2.5, "confirmed_loss_used_usd": 2.5},
    }
    assert validate_pnl(matching) == []
    mismatching = {
        "bot_state": {"daily_realized_pnl": -2.5, "daily_loss_used_usd": 2.5},
        "daily_summary": {"confirmed_realized_pnl": -1.5, "confirmed_loss_used_usd": 1.5},
    }
    assert len(validate_pnl(mismatching)) == 2
