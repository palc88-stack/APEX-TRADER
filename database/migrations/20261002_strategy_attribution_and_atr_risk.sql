-- APEX-TRADER: signal attribution and ATR-based risk provenance.
-- Additive and safe to apply to existing Testnet deployments.

CREATE TABLE IF NOT EXISTS public.strategy_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  symbol VARCHAR(20) NOT NULL,
  mode VARCHAR(20),
  strategy VARCHAR(40),
  strategy_subtype VARCHAR(80) NOT NULL,
  action VARCHAR(10) NOT NULL,
  confidence DECIMAL(6, 4),
  rule_score DECIMAL(6, 4),
  reason TEXT,
  entry_price DECIMAL(30, 12),
  atr_value DECIMAL(30, 12),
  atr_multiplier DECIMAL(10, 4),
  stop_distance DECIMAL(30, 12),
  stop_loss DECIMAL(30, 12),
  take_profit DECIMAL(30, 12),
  risk_budget_usd DECIMAL(18, 8),
  status VARCHAR(20) NOT NULL DEFAULT 'candidate',
  trade_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.pending_signals
  ADD COLUMN IF NOT EXISTS strategy VARCHAR(40),
  ADD COLUMN IF NOT EXISTS strategy_subtype VARCHAR(80),
  ADD COLUMN IF NOT EXISTS confidence DECIMAL(6, 4),
  ADD COLUMN IF NOT EXISTS reason TEXT;

ALTER TABLE public.trades
  ADD COLUMN IF NOT EXISTS atr_value DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS atr_multiplier DECIMAL(10, 4),
  ADD COLUMN IF NOT EXISTS stop_distance DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS risk_budget_usd DECIMAL(18, 8),
  ADD COLUMN IF NOT EXISTS signal_id UUID;

CREATE INDEX IF NOT EXISTS idx_strategy_signals_attribution
  ON public.strategy_signals (strategy, strategy_subtype, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_symbol_created
  ON public.strategy_signals (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_signal_id
  ON public.trades (signal_id) WHERE signal_id IS NOT NULL;

COMMENT ON TABLE public.strategy_signals IS 'Immutable-ish audit trail of accepted non-HOLD strategy signals; not a fill ledger.';
COMMENT ON COLUMN public.strategy_signals.confidence IS 'Uncalibrated deterministic rule score; not a probability.';
COMMENT ON COLUMN public.trades.risk_budget_usd IS 'Maximum planned loss budget before fees/slippage, derived from balance or fixed USD cap.';
COMMENT ON COLUMN public.trades.stop_distance IS 'Absolute entry-to-stop price distance used for sizing.';
