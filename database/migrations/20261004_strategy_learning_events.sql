-- APEX-TRADER: phase 1 strategy learning ledger.
-- This is an audit/analytics table only; it never authorizes or changes orders.

CREATE TABLE IF NOT EXISTS public.strategy_learning_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type VARCHAR(32) NOT NULL,
  trade_id TEXT REFERENCES public.trades(id) ON DELETE SET NULL,
  symbol VARCHAR(40),
  strategy VARCHAR(40),
  strategy_subtype VARCHAR(80),
  outcome VARCHAR(32),
  realized_pnl DECIMAL(18, 8),
  fee_amount DECIMAL(18, 8),
  slippage_bps DECIMAL(18, 8),
  error_code VARCHAR(80),
  error_message TEXT,
  error_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  features JSONB NOT NULL DEFAULT '{}'::jsonb,
  model_version VARCHAR(64) NOT NULL DEFAULT 'rules-v1',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT strategy_learning_events_type_check CHECK (
    event_type IN ('trade_outcome', 'execution_error', 'data_quality', 'reconciliation')
  )
);

CREATE INDEX IF NOT EXISTS idx_strategy_learning_events_strategy
  ON public.strategy_learning_events (strategy, strategy_subtype, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_learning_events_trade
  ON public.strategy_learning_events (trade_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_learning_events_type
  ON public.strategy_learning_events (event_type, created_at DESC);

ALTER TABLE public.strategy_learning_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.strategy_learning_events FROM anon, authenticated;
GRANT SELECT ON TABLE public.strategy_learning_events TO authenticated;
DROP POLICY IF EXISTS strategy_learning_events_authenticated_read
  ON public.strategy_learning_events;
CREATE POLICY strategy_learning_events_authenticated_read
  ON public.strategy_learning_events FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS strategy_learning_events_service_role_all
  ON public.strategy_learning_events;
CREATE POLICY strategy_learning_events_service_role_all
  ON public.strategy_learning_events FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE public.strategy_learning_events IS
  'Append-only analytics ledger for strategy outcomes and operational errors; never an order or fill authority.';
COMMENT ON COLUMN public.strategy_learning_events.features IS
  'Observed real exchange-derived/context features at the event; not synthetic training data.';
COMMENT ON COLUMN public.strategy_learning_events.model_version IS
  'Rules/model attribution for later comparison; phase 1 uses rules-v1 and no adaptive execution.';
