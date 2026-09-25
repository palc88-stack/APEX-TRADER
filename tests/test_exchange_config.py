# tests/test_exchange_config.py — اختبارات متوافقة مع ExchangeConfig الحالي
# البلوك الأصلي كان يستخدم واجهة غير موجودة (trading_exchanges + validate())

import pytest
from bot.config import ExchangeConfig


def test_exchange_config_enabled_exchanges_binance(monkeypatch):
    """binance สมมติให้มี BINANCE_API_KEY — تتوقع_LIST مدعومة"""
    monkeypatch.setenv("BINANCE_API_KEY", "binance-key")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "binance-secret")
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_SECRET_KEY", raising=False)

    ec = ExchangeConfig()
    assert "binance" in ec.enabled_exchanges()


def test_exchange_config_no_keys_defaults_to_binance(monkeypatch):
    """عندما لا توجد مفاتيح — الافتراض هو Binance"""
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_SECRET_KEY", raising=False)
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_SECRET_KEY", raising=False)
    monkeypatch.delenv("TRADING_EXCHANGES", raising=False)

    ec = ExchangeConfig()
    assert ec.enabled_exchanges() == ["binance"]


def test_exchange_config_primary_exchange_default(monkeypatch):
    monkeypatch.delenv("PRIMARY_EXCHANGE", raising=False)
    ec = ExchangeConfig()
    assert ec.primary_exchange() == "binance"


def test_exchange_config_primary_exchange_custom(monkeypatch):
    monkeypatch.setenv("PRIMARY_EXCHANGE", "bybit")
    ec = ExchangeConfig()
    assert ec.primary_exchange() == "bybit"


def test_exchange_config_binance_testnet_default(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET", raising=False)
    ec = ExchangeConfig()
    assert ec.binance_testnet is True


def test_exchange_config_binance_testnet_custom(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    ec = ExchangeConfig()
    assert ec.binance_testnet is False
