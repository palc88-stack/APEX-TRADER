from bot.learning.shadow import recommend_shadow_action


def test_shadow_mode_is_observational_and_keeps_valid_candidate():
    result = recommend_shadow_action(
        {
            "action": "LONG",
            "confidence": 0.8,
            "indicators": {"atr_value": 12.0},
        },
        min_confidence=0.65,
    )
    assert result["candidate_action"] == "LONG"
    assert result["shadow_action"] == "LONG"
    assert result["decision"] == "observation_only"
    assert result["model_version"] == "shadow-rules-v1"


def test_shadow_mode_rejects_incomplete_candidate_as_hold():
    result = recommend_shadow_action(
        {"action": "SHORT", "confidence": 0.4, "indicators": {"atr_value": 0}},
        min_confidence=0.65,
    )
    assert result["shadow_action"] == "HOLD"
    assert result["shadow_confidence"] == 0.0
    assert result["decision"] == "observation_only"


def test_learning_report_keeps_shadow_outcomes_out_of_pnl():
    from datetime import datetime, timezone
    from scripts.generate_strategy_learning_report import build_report

    report = build_report(
        [
            {
                "event_type": "shadow_signal",
                "features": {"candidate_action": "LONG", "shadow_action": "HOLD"},
                "model_version": "shadow-rules-v1",
            },
            {
                "event_type": "trade_outcome",
                "outcome": "win",
                "realized_pnl": "2.0",
                "fee_amount": "0.2",
                "strategy": "SCALPING",
                "strategy_subtype": "momentum",
                "symbol": "BTC/USDT",
            },
        ],
        datetime.now(timezone.utc),
        datetime.now(timezone.utc),
    )
    assert report["overall"]["closed_outcomes"] == 1
    assert report["shadow_mode"]["signals"] == 1
    assert report["shadow_mode"]["execution_impact"] == "none; observational only"
