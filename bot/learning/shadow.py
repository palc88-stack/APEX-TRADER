"""Observational Shadow Mode policy.

The policy is deliberately conservative and deterministic. It produces an
analytical recommendation only; callers must never use it as an order gate.
"""
from __future__ import annotations

from typing import Any, Dict


def recommend_shadow_action(
    signal: Dict[str, Any],
    *,
    min_confidence: float = 0.65,
) -> Dict[str, Any]:
    action = str(signal.get("action") or "HOLD").upper()
    confidence = float(signal.get("confidence") or 0.0)
    indicators = signal.get("indicators") or {}
    atr_value = float(indicators.get("atr_value") or 0.0)

    # No historical model is allowed to invent a decision. Until enough real
    # outcomes exist, Shadow Mode records the current deterministic candidate
    # and labels it as observation-only. Invalid/incomplete candidates are
    # conservatively represented as HOLD for later comparison.
    valid_candidate = action in {"BUY", "SELL", "LONG", "SHORT"}
    recommendation = action if valid_candidate and atr_value > 0 and confidence >= min_confidence else "HOLD"
    return {
        "candidate_action": action,
        "candidate_confidence": confidence,
        "shadow_action": recommendation,
        "shadow_confidence": confidence if recommendation != "HOLD" else 0.0,
        "decision": "observation_only",
        "reason": (
            "rules-v1 candidate observed; no adaptive model applied"
            if recommendation != "HOLD"
            else "candidate failed conservative shadow completeness gate"
        ),
        "model_version": "shadow-rules-v1",
    }
