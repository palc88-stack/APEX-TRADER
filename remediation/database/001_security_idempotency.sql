-- APEX-TRADER security/idempotency migration
-- Apply only in an isolated Supabase project first, then review grants.

ALTER TABLE IF EXISTS public.bot_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.pending_signals ENABLE ROW LEVEL SECURITY;

-- Dashboard users may read only when authenticated. No client write policies are defined.
DROP POLICY IF EXISTS authenticated_read_bot_state ON public.bot_state;
CREATE POLICY authenticated_read_bot_state
  ON public.bot_state FOR SELECT TO authenticated
  USING (true);

DROP POLICY IF EXISTS authenticated_read_trades ON public.trades;
CREATE POLICY authenticated_read_trades
  ON public.trades FOR SELECT TO authenticated
  USING (true);

-- Pending signals are not exposed to browser clients.
REVOKE ALL ON TABLE public.pending_signals FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON TABLE public.bot_state FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON TABLE public.trades FROM anon, authenticated;

-- Idempotency and bounded state transitions.
CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_signals_webhook_id
  ON public.pending_signals (webhook_id)
  WHERE webhook_id IS NOT NULL;

ALTER TABLE public.pending_signals
  ADD COLUMN IF NOT EXISTS processing_owner TEXT,
  ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error TEXT;

ALTER TABLE public.pending_signals
  DROP CONSTRAINT IF EXISTS pending_signals_status_check;
ALTER TABLE public.pending_signals
  ADD CONSTRAINT pending_signals_status_check
  CHECK (status IN ('pending', 'processing', 'processed', 'failed'));

ALTER TABLE public.pending_signals
  DROP CONSTRAINT IF EXISTS pending_signals_side_check;
ALTER TABLE public.pending_signals
  ADD CONSTRAINT pending_signals_side_check
  CHECK (lower(side) IN ('buy', 'sell'));

ALTER TABLE public.pending_signals
  DROP CONSTRAINT IF EXISTS pending_signals_action_check;
ALTER TABLE public.pending_signals
  ADD CONSTRAINT pending_signals_action_check
  CHECK (upper(action) IN ('BUY', 'SELL', 'LONG', 'SHORT'));

ALTER TABLE public.pending_signals
  DROP CONSTRAINT IF EXISTS pending_signals_price_check;
ALTER TABLE public.pending_signals
  ADD CONSTRAINT pending_signals_price_check
  CHECK (price IS NULL OR price > 0);

-- Service-role/backend RPCs must perform claim/update operations. Do not grant these to anon.
CREATE OR REPLACE FUNCTION public.claim_pending_signal(p_signal_id INTEGER, p_owner TEXT)
RETURNS SETOF public.pending_signals
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE public.pending_signals
     SET status = 'processing',
         processing_owner = p_owner,
         processing_started_at = now(),
         attempt_count = attempt_count + 1
   WHERE id = p_signal_id
     AND (
       status = 'pending'
       OR (status = 'processing' AND processing_started_at < now() - interval '10 minutes')
     )
  RETURNING *;
$$;

REVOKE ALL ON FUNCTION public.claim_pending_signal(INTEGER, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_pending_signal(INTEGER, TEXT) TO service_role;
