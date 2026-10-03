"""Opt-in Supabase integration tests for strategy_signals RLS.

These tests are skipped by default. Enable them only against the intended
Supabase project with RUN_SUPABASE_INTEGRATION=1. The tests create one
uniquely-keyed candidate signal and always remove it in a finally block.
"""
import os
import uuid

import pytest
from supabase import create_client

from bot.data.state_manager import StateManager

pytestmark = pytest.mark.integration


def _require_url():
    if os.getenv("RUN_SUPABASE_INTEGRATION") != "1":
        pytest.skip("Set RUN_SUPABASE_INTEGRATION=1 to run Supabase integration tests")
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_WRITE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_key:
        pytest.skip("SUPABASE_URL and SUPABASE_WRITE_KEY are required")
    return url, service_key


def _signal(key):
    return {
        "idempotency_key": key,
        "symbol": "BTC/USDT:USDT",
        "mode": "testnet",
        "strategy": "TREND",
        "strategy_subtype": "rls_integration_probe",
        "action": "LONG",
        "confidence": 0.5,
        "rule_score": 0.5,
        "entry_price": 60000,
        "atr_value": 120,
        "atr_multiplier": 2,
        "stop_distance": 240,
        "risk_budget_usd": 1,
        "status": "candidate",
    }


def test_bot_state_manager_service_role_can_write_and_read_signal(monkeypatch):
    url, service_key = _require_url()
    key = f"integration:rls:{uuid.uuid4()}"
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_WRITE_KEY", service_key)
    manager = StateManager()
    assert manager.client is not None

    try:
        assert manager.record_strategy_signal(_signal(key)) is True
        result = (
            manager.client.table("strategy_signals")
            .select("id,idempotency_key,strategy_subtype,status")
            .eq("idempotency_key", key)
            .limit(1)
            .execute()
        )
        assert len(result.data or []) == 1
        assert result.data[0]["strategy_subtype"] == "rls_integration_probe"
    finally:
        manager.client.table("strategy_signals").delete().eq(
            "idempotency_key", key
        ).execute()


def test_anon_role_cannot_read_strategy_signals():
    url, _ = _require_url()
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    if not anon_key:
        pytest.skip("SUPABASE_ANON_KEY is required for anon RLS assertion")

    anon = create_client(url, anon_key)
    with pytest.raises(Exception):
        anon.table("strategy_signals").select("id").limit(1).execute()


def test_authenticated_role_can_read_strategy_signals():
    url, _ = _require_url()
    email = os.getenv("SUPABASE_TEST_EMAIL")
    password = os.getenv("SUPABASE_TEST_PASSWORD")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    if not all((email, password, anon_key)):
        pytest.skip(
            "SUPABASE_ANON_KEY, SUPABASE_TEST_EMAIL and SUPABASE_TEST_PASSWORD "
            "are required for authenticated RLS assertion"
        )

    client = create_client(url, anon_key)
    client.auth.sign_in_with_password({"email": email, "password": password})
    result = client.table("strategy_signals").select("id").limit(1).execute()
    assert result.data is not None
