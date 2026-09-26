# Cloudflare deployment

The repository uses one Cloudflare Worker named `pal` for the dashboard only.

- Dashboard: `https://pal.pal-c88.workers.dev/`
- The Worker serves the built `web/dist` assets for `GET` and `HEAD` requests.
- Non-browser methods return `405`.

TradingView and the Worker webhook have been removed. The Python bot polls the configured exchange directly through `ccxt`; it does not depend on `pending_signals`, `WEBHOOK_SECRET`, or an inbound trading webhook.

The browser build contains only the public Supabase URL and publishable key. Backend write keys and exchange credentials must never be included in `web/dist` or source control.
