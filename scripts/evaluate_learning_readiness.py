#!/usr/bin/env python3
"""Evaluate whether real Testnet data is sufficient for a learning candidate.

This gate never changes bot configuration. It returns a report and deliberately
stays NOT_READY when the sample or out-of-sample evidence is missing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def evaluate(report: dict, *, min_outcomes: int = 50) -> dict:
    overall = report.get("overall") or {}
    outcomes = int(overall.get("closed_outcomes") or 0)
    net = overall.get("net_after_recorded_fees")
    profit_factor = overall.get("profit_factor")
    sufficient_sample = outcomes >= min_outcomes
    positive_net = isinstance(net, (int, float)) and net > 0
    valid_profit_factor = isinstance(profit_factor, (int, float)) and profit_factor > 1
    # A real out-of-sample artifact is intentionally required separately; the
    # daily event report is in-sample/observational and cannot satisfy it.
    out_of_sample_validated = bool(report.get("out_of_sample_validation", {}).get("validated"))
    ready = sufficient_sample and positive_net and valid_profit_factor and out_of_sample_validated
    return {
        "status": "READY_FOR_MANUAL_REVIEW" if ready else "NOT_READY",
        "adaptive_execution_enabled": False,
        "shadow_mode_only": True,
        "requirements": {
            "minimum_confirmed_outcomes": min_outcomes,
            "confirmed_outcomes": outcomes,
            "sufficient_sample": sufficient_sample,
            "positive_net_after_fees": positive_net,
            "profit_factor_above_1": valid_profit_factor,
            "out_of_sample_validated": out_of_sample_validated,
        },
        "reason": (
            "All statistical gates passed; manual review is still required."
            if ready
            else "Insufficient real evidence; keep adaptive execution disabled."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-outcomes", type=int, default=50)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = evaluate(report, min_outcomes=args.min_outcomes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
