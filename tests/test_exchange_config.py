import pytest

from bot.config import ExchangeConfig


def test_bybit_configuration_requires_bybit_credentials(
    monkeypatch,
):
    monkeypatch.setenv(
        "TRADING_EXCHANGES",
        "bybit",
    )
    monkeypatch.setenv(
        "BYBIT_API_KEY",
        "bybit-key",
    )
    monkeypatch.setenv(
        "BYBIT_SECRET_KEY",
        "bybit-secret",
    )

    exchange_config = ExchangeConfig()

    assert exchange_config.trading_exchanges == [
        "bybit"
    ]
    assert exchange_config.validate() is True


def test_invalid_exchange_is_rejected(monkeypatch):
    monkeypatch.setenv(
        "TRADING_EXCHANGES",
        "unknown",
    )

    with pytest.raises(ValueError):
        ExchangeConfig()
