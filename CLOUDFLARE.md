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

These secrets are used only by scheduled server-side code and must never be
placed in `web/dist` or browser environment variables.

TradingView and the Worker webhook have been removed. The Python bot polls the
configured exchange directly through `ccxt`; it does not depend on
`pending_signals`, `WEBHOOK_SECRET`, or an inbound trading webhook.

The browser build contains only the public Supabase URL and publishable key.
Backend write keys and exchange credentials must never be included in
`web/dist` or source control.
