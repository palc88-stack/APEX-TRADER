"""Transparent, observation-only committee summary for existing APEX shadow checks.

This module does not generate orders, size positions, or change a strategy signal.
Its votes are summaries of existing deterministic Shadow checks, not independent
models or probabilities.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict


MODEL_VERSION = "apex-shadow-committee-v1"

_ROLE_CHECKS = (
    ("trend", "hunter_trend"),
    ("entry_quality", "hunter_rsi"),
    ("participation", "filter_volume"),
    ("momentum", "filter_macd"),
    ("scalping_pattern", "scalping_setup"),
)


def _normalize_action(value: Any) -> str | None:
    action = str(value or "").strip().upper()
    if action.startswith("TRADEDIRECTION."):
        action = action.split(".", 1)[1]
    if action in {"LONG", "BUY"}:
        return "LONG"
    if action in {"SHORT", "SELL"}:
        return "SHORT"
    return None


def build_committee_assessment(observation: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize existing Shadow rule checks as explainable advisory votes.

    `scalping_setup` is only considered when the selected strategy/subtype is a
    scalping or mean-reversion family; otherwise that seat abstains. Missing or
    non-boolean inputs always abstain, rather than being coerced to a vote.
    """
    features = observation.get("features")
    features = features if isinstance(features, Mapping) else {}
    checks = features.get("checks")
    checks = checks if isinstance(checks, Mapping) else {}
    candidate_action = _normalize_action(observation.get("candidate_action"))

    family = " ".join(
        str(observation.get(key) or "")
        for key in ("strategy", "strategy_subtype")
    ).upper()
    is_scalping = "SCALP" in family or "MEAN_REVERSION" in family

    votes: Dict[str, Dict[str, str]] = {}
    for role, check_name in _ROLE_CHECKS:
        raw_value = checks.get(check_name)
        if role == "scalping_pattern" and not is_scalping:
            vote = "ABSTAIN"
        elif candidate_action is None or not isinstance(raw_value, bool):
            vote = "ABSTAIN"
        else:
            vote = "SUPPORT" if raw_value else "CHALLENGE"
        votes[role] = {"vote": vote, "source_check": check_name}

    support_count = sum(vote["vote"] == "SUPPORT" for vote in votes.values())
    challenge_count = sum(vote["vote"] == "CHALLENGE" for vote in votes.values())
    abstain_count = sum(vote["vote"] == "ABSTAIN" for vote in votes.values())
    directional_votes = support_count + challenge_count

    if candidate_action is None:
        classification = "NO_CANDIDATE"
    elif directional_votes < 2:
        classification = "INSUFFICIENT_EVIDENCE"
    elif support_count > challenge_count:
        classification = "LEAN_SUPPORT"
    elif challenge_count > support_count:
        classification = "LEAN_CHALLENGE"
    else:
        classification = "MIXED"

    return {
        "model_version": MODEL_VERSION,
        "candidate_action": candidate_action or "NONE",
        "classification": classification,
        "support_count": support_count,
        "challenge_count": challenge_count,
        "abstain_count": abstain_count,
        # Descriptive share of the existing checks only; never a probability.
        "rule_agreement_share": (
            round(support_count / directional_votes, 4)
            if directional_votes
            else None
        ),
        "votes": votes,
        "advisory_only": True,
        "execution_authority": False,
        "source": "existing_apex_shadow_checks",
        "note": (
            "Summarizes existing deterministic checks; not an independent model, "
            "probability, trade approval, or execution instruction."
        ),
    }
