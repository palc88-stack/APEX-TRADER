-- APEX-TRADER: independent, observation-only Shadow signal ledger.
-- Never an order, fill, realized PnL, or risk-accounting authority.
CREATE TABLE IF NOT EXISTS public.shadow_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  symbol VARCHAR(40) NOT NULL,
  timeframe VARCHAR(12) NOT NULL,
  strategy VARCHAR(40) NOT NULL,
  strategy_subtype VARCHAR(80),
  candle_closed_at TIMESTAMPTZ NOT NULL,
  candidate_action VARCHAR(12) NOT NULL,
  classification VARCHAR(24) NOT NULL CHECK (classification IN ('NO_SIGNAL','NEAR_MISS','SHADOW_CANDIDATE')),
  model_version VARCHAR(64) NOT NULL,
  confidence NUMERIC,
  rule_score NUMERIC,
  entry_price NUMERIC NOT NULL,
  stop_loss NUMERIC,
  take_profit_1 NUMERIC,
  take_profit_2 NUMERIC,
  atr_value NUMERIC,
  atr_pct NUMERIC,
  rsi NUMERIC,
  ema_50 NUMERIC,
  ema_200 NUMERIC,
  macd NUMERIC,
  macd_signal NUMERIC,
  bb_position NUMERIC,
  bb_width NUMERIC,
  volume_ratio NUMERIC,
  failed_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
  features JSONB NOT NULL DEFAULT '{}'::jsonb,
  status VARCHAR(24) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','WON','LOST','TIMEOUT','INVALIDATED','INSUFFICIENT_DATA')),
  mfe_pct NUMERIC,
  mae_pct NUMERIC,
  net_return_pct NUMERIC,
  exit_reason VARCHAR(64),
  evaluated_candles INTEGER NOT NULL DEFAULT 0,
  horizon_candles INTEGER NOT NULL DEFAULT 12,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  evaluated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_shadow_signals_open ON public.shadow_signals(status, candle_closed_at);
CREATE INDEX IF NOT EXISTS idx_shadow_signals_strategy ON public.shadow_signals(strategy, strategy_subtype, created_at DESC);
ALTER TABLE public.shadow_signals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.shadow_signals FROM anon, authenticated;
GRANT SELECT ON TABLE public.shadow_signals TO authenticated;
DROP POLICY IF EXISTS shadow_signals_authenticated_read ON public.shadow_signals;
CREATE POLICY shadow_signals_authenticated_read ON public.shadow_signals FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS shadow_signals_service_role_all ON public.shadow_signals;
CREATE POLICY shadow_signals_service_role_all ON public.shadow_signals FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMENT ON TABLE public.shadow_signals IS 'Closed-candle paper observations only; never execution or realized PnL authority.';
