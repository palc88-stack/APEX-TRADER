from bot.learning.committee_shadow import build_committee_assessment


def _observation(**overrides):
    result = {
        "candidate_action": "LONG",
        "strategy": "HUNTER",
        "strategy_subtype": "trend",
        "features": {
            "checks": {
                "hunter_trend": True,
                "hunter_rsi": True,
                "filter_volume": True,
                "filter_macd": False,
                "scalping_setup": False,
            }
        },
    }
    result.update(overrides)
    return result


def test_committee_summarizes_existing_checks_without_authorizing_trade():
    assessment = build_committee_assessment(_observation())

    assert assessment["model_version"] == "apex-shadow-committee-v1"
    assert assessment["candidate_action"] == "LONG"
    assert assessment["classification"] == "LEAN_SUPPORT"
    assert assessment["support_count"] == 3
    assert assessment["challenge_count"] == 1
    assert assessment["abstain_count"] == 1
    assert assessment["rule_agreement_share"] == 0.75
    assert assessment["votes"]["scalping_pattern"]["vote"] == "ABSTAIN"
    assert assessment["advisory_only"] is True
    assert assessment["execution_authority"] is False
    assert "probability" in assessment["note"]
    assert not {"order", "quantity", "size_multiplier", "approved"} & assessment.keys()


def test_committee_abstains_on_missing_or_non_boolean_checks():
    assessment = build_committee_assessment(
        _observation(
            features={"checks": {"hunter_trend": True, "filter_macd": "false"}}
        )
    )

    assert assessment["classification"] == "INSUFFICIENT_EVIDENCE"
    assert assessment["support_count"] == 1
    assert assessment["challenge_count"] == 0
    assert assessment["rule_agreement_share"] == 1.0
    assert assessment["votes"]["momentum"]["vote"] == "ABSTAIN"


def test_committee_normalizes_buy_and_short_enum_labels():
    buy = build_committee_assessment(_observation(candidate_action="BUY"))
    short = build_committee_assessment(_observation(candidate_action="TradeDirection.SHORT"))

    assert buy["candidate_action"] == "LONG"
    assert short["candidate_action"] == "SHORT"


def test_committee_has_no_directional_vote_without_candidate():
    assessment = build_committee_assessment(_observation(candidate_action="HOLD"))

    assert assessment["candidate_action"] == "NONE"
    assert assessment["classification"] == "NO_CANDIDATE"
    assert assessment["support_count"] == 0
    assert assessment["challenge_count"] == 0
    assert assessment["abstain_count"] == 5
    assert assessment["rule_agreement_share"] is None
