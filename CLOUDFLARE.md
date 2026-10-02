# Cloudflare deployment

The repository uses one Cloudflare Worker named `pal` for the dashboard and
read-only scheduled supervision. The scheduled jobs never place, cancel, or
close exchange orders.

- Dashboard: `https://pal.pal-c88.workers.dev/`
- The Worker serves the built `web/dist` assets for `GET` and `HEAD` requests.
- Non-browser methods return `405`.

## Cron jobs (UTC)

- `*/5 * * * *`: read-only health and unresolved-reconciliation monitor.
- `0 */4 * * *`: refresh the top-20 Binance USD-M liquidity universe.
- `0 2 * * *`: daily read-only Binance/Supabase reconciliation and Telegram alert.

Before the daily reconciliation runs, the Worker acquires the shared
`apex-trading-execution` lease in Supabase. If GitHub Actions or another owner
holds it, the Worker skips the run without touching orders. The four-hour
universe refresh uses the separate `apex-universe-refresh` lease.

The Worker remains read-only with respect to exchange orders: it never opens,
cancels, or closes an order. The shared trading lease is a guardrail so a
future write-capable reconciliation path cannot run concurrently with the
GitHub Actions bot.

The four-hour universe schedule is intentionally removed from GitHub Actions to
avoid duplicate snapshot activation. `.github/workflows/universe-refresh.yml`
remains available through manual dispatch as a fallback.

## Required Worker Secrets

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `BINANCE_API_KEY`
- `BINANCE_SECRET_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Non-secret Worker variables

The Worker configuration carries these non-secret observability and Testnet
guardrail variables:

- `SUBTYPE_REPORT_BATCH_SIZE=10`
- `ATR_PERIOD=14`
- `ATR_STOP_MULTIPLIER=2.0`
- `MAX_LEVERAGE=5`
- `MAX_RISK_PER_TRADE_PCT=1.0`
- `MAX_RISK_PER_TRADE_USD=10.0`

The Worker remains read-only and does not place exchange orders. The Python bot
receives the authoritative risk settings through GitHub Actions environment
variables; the Worker values are for monitoring and health consistency.

These secrets are used only by scheduled server-side code and must never be
placed in `web/dist` or browser environment variables.

TradingView and the Worker webhook have been removed. The Python bot polls the
configured exchange directly through `ccxt`; it does not depend on
`pending_signals`, `WEBHOOK_SECRET`, or an inbound trading webhook.

The browser build contains only the public Supabase URL and publishable key.
Backend write keys and exchange credentials must never be included in
`web/dist` or source control.
