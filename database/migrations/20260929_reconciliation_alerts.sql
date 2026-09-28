-- Idempotent Telegram alert state for automatic, read-only reconciliation.
-- The bot still fails closed: it never adopts or closes an orphan automatically.
ALTER TABLE public.bot_state
  ADD COLUMN IF NOT EXISTS reconciliation_alert_key TEXT;

ALTER TABLE public.bot_state
  ADD COLUMN IF NOT EXISTS reconciliation_alerted_at TIMESTAMPTZ;

COMMENT ON COLUMN public.bot_state.reconciliation_alert_key IS
  'Stable key of the last reconciliation state sent to Telegram';
