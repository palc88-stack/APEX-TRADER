from scripts.analyze_subtype_performance import summarize_trades


def test_subtype_summary_excludes_unconfirmed_and_groups_metrics():
    report = summarize_trades([
        {"status": "CLOSED", "pnl_source": "exchange_fill", "strategy_subtype": "scalp", "pnl": "2.0", "exit_slippage_bps": 1},
        {"status": "CLOSED", "pnl_source": "exchange_fill", "strategy_subtype": "scalp", "pnl": "-1.0", "exit_slippage_bps": 3},
        {"status": "CLOSED", "pnl_source": "unconfirmed", "strategy_subtype": "scalp", "pnl": 99},
        {"status": "OPEN", "pnl_source": "exchange_fill", "strategy_subtype": "trend", "pnl": 5},
    ])
    assert report["confirmed_closed_trades"] == 2
    assert report["completed_milestone"] == 0
    scalp = report["subtypes"][0]
    assert scalp["strategy_subtype"] == "scalp"
    assert scalp["winning_trades"] == 1
    assert scalp["losing_trades"] == 1
    assert scalp["profit_factor"] == 2.0
    assert scalp["expectancy"] == 0.5


def test_subtype_summary_marks_each_ten_trade_milestone():
    trades = [
        {
            "status": "CLOSED",
            "pnl_source": "exchange_fill",
            "strategy_subtype": "trend",
            "pnl": 1.0 if index % 2 else -0.5,
        }
        for index in range(20)
    ]
    report = summarize_trades(trades)
    assert report["confirmed_closed_trades"] == 20
    assert report["completed_milestone"] == 20
    assert report["next_milestone"] == 30
    assert report["milestone_reached"] is True
