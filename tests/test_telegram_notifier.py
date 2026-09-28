import pytest

from bot.notifications.telegram_notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_daily_report_builds_without_network(monkeypatch):
    notifier = TelegramNotifier()
    messages = []

    async def capture(message, parse_mode="HTML"):
        messages.append((message, parse_mode))
        return True

    monkeypatch.setattr(notifier, "send", capture)
    await notifier.send_daily_report(
        {"win_rate": 60, "net_pnl": 1.5, "total_trades": 2,
         "winning_trades": 1, "losing_trades": 1, "total_fees": 0.2},
        balance=100.0,
    )

    assert len(messages) == 1
    assert "تقرير يومي" in messages[0][0]
