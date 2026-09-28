-- APEX Trader: provenance, reconciliation, order identity and strategy metadata.
-- Safe/idempotent DDL. Apply with Supabase migration tooling.

ALTER TABLE public.trades
  ADD COLUMN IF NOT EXISTS strategy VARCHAR(40),
  ADD COLUMN IF NOT EXISTS signal_confidence DECIMAL(6, 4),
  ADD COLUMN IF NOT EXISTS signal_reason TEXT,
  ADD COLUMN IF NOT EXISTS entry_order_id TEXT,
  ADD COLUMN IF NOT EXISTS entry_client_order_id TEXT,
  ADD COLUMN IF NOT EXISTS stop_algo_id TEXT,
  ADD COLUMN IF NOT EXISTS take_profit_algo_id TEXT,
  ADD COLUMN IF NOT EXISTS closing_order_id TEXT,
  ADD COLUMN IF NOT EXISTS entry_price_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS entry_quantity_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS entry_fee_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS exit_price_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS exit_quantity_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS exit_fee_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS pnl_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  ADD COLUMN IF NOT EXISTS reconciliation_note TEXT;

ALTER TABLE public.trades DROP CONSTRAINT IF EXISTS trades_status_check;
ALTER TABLE public.trades ADD CONSTRAINT trades_status_check
  CHECK (status IN ('OPEN', 'CLOSED', 'NEEDS_RECONCILIATION'));

CREATE TABLE IF NOT EXISTS public.partial_closes (
  id BIGSERIAL PRIMARY KEY,
  trade_id TEXT NOT NULL REFERENCES public.trades(id) ON DELETE CASCADE,
  reason VARCHAR(30) NOT NULL,
  price DECIMAL(18, 8),
  amount_closed DECIMAL(18, 8),
  pnl DECIMAL(18, 4),
  fee DECIMAL(18, 8),
  price_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  quantity_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  fee_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  pnl_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
  exchange_order_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_partial_closes_trade_id
  ON public.partial_closes (trade_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_reconciliation
  ON public.trades (status) WHERE status = 'NEEDS_RECONCILIATION';
CREATE INDEX IF NOT EXISTS idx_trades_strategy
  ON public.trades (strategy, opened_at DESC);

ALTER TABLE public.partial_closes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS authenticated_read_partial_closes ON public.partial_closes;
CREATE POLICY authenticated_read_partial_closes ON public.partial_closes
  FOR SELECT TO authenticated USING (true);
REVOKE ALL ON TABLE public.partial_closes FROM anon, authenticated;
GRANT SELECT ON TABLE public.partial_closes TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON TABLE public.partial_closes FROM authenticated;

-- Existing records are deliberately left unconfirmed. No historical source is invented.
