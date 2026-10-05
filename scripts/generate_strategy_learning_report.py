#!/usr/bin/env python3
"""Generate a read-only strategy learning report from real Supabase events.

This script is intentionally observational: it never writes to Supabase, sends
orders, or changes strategy/risk configuration. It reports only confirmed trade
outcomes and recorded operational errors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PAGE_SIZE = 1000


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fetch_events(base_url: str, key: str, start: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    endpoint = f"{base_url.rstrip('/')}/rest/v1/strategy_learning_events"
    while True:
        params = urlencode(
            {
                "select": "event_type,trade_id,symbol,strategy,strategy_subtype,outcome,realized_pnl,fee_amount,slippage_bps,error_code,error_tags,features,model_version,created_at",
                "created_at": f"gte.{start.isoformat()}",
                "order": "created_at.desc",
                "limit": str(PAGE_SIZE),
                "offset": str(offset),
            }
        )
        request = Request(
            f"{endpoint}?{params}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urlopen(request, timeout=30) as response:  # noqa: S310 - URL comes from SUPABASE_URL
            page = json.loads(response.read().decode("utf-8"))
        if not isinstance(page, list):
            raise RuntimeError("Supabase returned a non-list learning event response")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [row for row in rows if row.get("event_type") == "trade_outcome"]
    wins = sum(row.get("outcome") == "win" for row in outcomes)
    losses = sum(row.get("outcome") == "loss" for row in outcomes)
    pnl = sum(_number(row.get("realized_pnl")) for row in outcomes)
    fees = sum(_number(row.get("fee_amount")) for row in outcomes)
    gross_profit = sum(max(_number(row.get("realized_pnl")), 0.0) for row in outcomes)
    gross_loss = abs(sum(min(_number(row.get("realized_pnl")), 0.0) for row in outcomes))
    return {
        "closed_outcomes": len(outcomes),
        "wins": wins,
        "losses": losses,
        "flats": len(outcomes) - wins - losses,
        "win_rate": round(wins / len(outcomes), 6) if outcomes else None,
        "realized_pnl": round(pnl, 8),
        "fees": round(fees, 8),
        "net_after_recorded_fees": round(pnl - fees, 8),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "expectancy": round(pnl / len(outcomes), 8) if outcomes else None,
    }


def _group_by(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "UNKNOWN")].append(row)
    return {key: _group_metrics(value) for key, value in sorted(groups.items())}


def build_report(rows: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    outcomes = [row for row in rows if row.get("event_type") == "trade_outcome"]
    errors = [row for row in rows if row.get("event_type") == "execution_error"]
    shadows = [row for row in rows if row.get("event_type") == "shadow_signal"]
    shadow_actions = Counter()
    shadow_candidates = Counter()
    for row in shadows:
        features = row.get("features") or {}
        if isinstance(features, dict):
            shadow_actions[str(features.get("shadow_action") or "UNKNOWN")] += 1
            shadow_candidates[str(features.get("candidate_action") or "UNKNOWN")] += 1
    tag_counts: Counter[str] = Counter()
    code_counts: Counter[str] = Counter()
    for row in errors:
        code_counts[str(row.get("error_code") or "UNKNOWN")] += 1
        tags = row.get("error_tags") or []
        if isinstance(tags, list):
            tag_counts.update(str(tag) for tag in tags)

    warnings: list[str] = []
    if len(outcomes) < 30:
        warnings.append("insufficient confirmed outcomes for strategy changes; keep Shadow Mode disabled")
    if outcomes and _group_metrics(outcomes)["net_after_recorded_fees"] < 0:
        warnings.append("net recorded PnL after fees is negative in the selected window")
    if not outcomes:
        warnings.append("no confirmed trade outcomes in the selected window")

    return {
        "report_type": "strategy_learning_daily",
        "generated_at": end.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "source": "supabase.strategy_learning_events",
        "data_policy": "real recorded events only; no synthetic or inferred fills",
        "execution_policy": "read_only_report; no strategy or risk mutation",
        "event_counts": dict(Counter(str(row.get("event_type") or "UNKNOWN") for row in rows)),
        "overall": _group_metrics(outcomes),
        "by_strategy": _group_by(outcomes, "strategy"),
        "by_strategy_subtype": _group_by(outcomes, "strategy_subtype"),
        "by_symbol": _group_by(outcomes, "symbol"),
        "by_outcome": dict(Counter(str(row.get("outcome") or "UNKNOWN") for row in outcomes)),
        "execution_errors": {
            "count": len(errors),
            "by_code": dict(code_counts),
            "by_tag": dict(tag_counts),
        },
        "shadow_mode": {
            "signals": len(shadows),
            "candidate_actions": dict(shadow_candidates),
            "shadow_actions": dict(shadow_actions),
            "execution_impact": "none; observational only",
        },
        "warnings": warnings,
        "model_versions": dict(Counter(str(row.get("model_version") or "UNKNOWN") for row in rows)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.days <= 0 or args.days > 365:
        parser.error("--days must be between 1 and 365")

    base_url = os.getenv("SUPABASE_URL", "").strip()
    key = (os.getenv("SUPABASE_WRITE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not base_url or not key:
        print("SUPABASE_URL and SUPABASE_WRITE_KEY are required", file=sys.stderr)
        return 2

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    rows = _fetch_events(base_url, key, start)
    report = build_report(rows, start, end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "events": len(rows), "outcomes": report["overall"]["closed_outcomes"], "warnings": report["warnings"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
