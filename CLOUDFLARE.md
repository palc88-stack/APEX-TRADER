# Cloudflare deployment

The repository uses **one Cloudflare Worker** named `pal` for both the dashboard and the webhook API.

- Dashboard: `https://pal.pal-c88.workers.dev/`
- Webhook endpoint: `https://pal.pal-c88.workers.dev/webhook`
- Alternative API path: `https://pal.pal-c88.workers.dev/api/webhook`

The root GET request is served by the `web/dist` assets binding. POST requests must use `/webhook` or `/api/webhook`; the root asset path may return `405` because it is handled by the static asset layer.

Required Worker secrets:

- `SUPABASE_URL`
- `SUPABASE_WRITE_KEY`
- `WEBHOOK_SECRET`

The webhook requires the `x-webhook-secret` header and validates the signal before inserting it into Supabase `pending_signals`. No Binance order is placed by the Worker.
