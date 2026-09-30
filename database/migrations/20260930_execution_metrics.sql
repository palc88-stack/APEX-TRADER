-- APEX-TRADER execution metrics
-- Additive migration for strategy attribution, fill provenance, and account-level PnL.

ALTER TABLE public.trades
  ADD COLUMN IF NOT EXISTS strategy_subtype VARCHAR(80),
  ADD COLUMN IF NOT EXISTS rule_score DECIMAL(6, 4),
  ADD COLUMN IF NOT EXISTS account_balance_at_entry DECIMAL(18, 8),
  ADD COLUMN IF NOT EXISTS pnl_account_pct DECIMAL(10, 4),
  ADD COLUMN IF NOT EXISTS entry_fee_currency VARCHAR(20),
  ADD COLUMN IF NOT EXISTS exit_fee_currency VARCHAR(20),
  ADD COLUMN IF NOT EXISTS entry_filled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS exit_filled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS entry_slippage_bps DECIMAL(18, 8),
  ADD COLUMN IF NOT EXISTS exit_slippage_bps DECIMAL(18, 8),
  ADD COLUMN IF NOT EXISTS entry_mark_price DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS exit_mark_price DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS entry_trigger_price DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS exit_trigger_price DECIMAL(30, 12);

ALTER TABLE public.trade_fills
  ADD COLUMN IF NOT EXISTS reference_price NUMERIC(30, 12),
  ADD COLUMN IF NOT EXISTS slippage_bps NUMERIC(18, 8),
  ADD COLUMN IF NOT EXISTS mark_price NUMERIC(30, 12),
  ADD COLUMN IF NOT EXISTS trigger_price NUMERIC(30, 12);

ALTER TABLE public.partial_closes
  ADD COLUMN IF NOT EXISTS fee_currency VARCHAR(20),
  ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS reference_price DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS slippage_bps DECIMAL(18, 8),
  ADD COLUMN IF NOT EXISTS mark_price DECIMAL(30, 12),
  ADD COLUMN IF NOT EXISTS trigger_price DECIMAL(30, 12);

CREATE INDEX IF NOT EXISTS idx_trades_strategy_subtype
  ON public.trades (strategy, strategy_subtype, opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_fills_exchange_fill_id
  ON public.trade_fills (exchange, exchange_fill_id)
  WHERE exchange_fill_id IS NOT NULL;

COMMENT ON COLUMN public.trades.strategy_subtype IS 'Specific rule family selected inside an aggregate strategy mode.';
COMMENT ON COLUMN public.trades.rule_score IS 'Uncalibrated deterministic rule score; not a probability.';
COMMENT ON COLUMN public.trades.pnl_account_pct IS 'Realized PnL as a percentage of account balance at entry.';
COMMENT ON COLUMN public.trade_fills.slippage_bps IS 'Signed fill minus reference price, expressed in basis points.';
