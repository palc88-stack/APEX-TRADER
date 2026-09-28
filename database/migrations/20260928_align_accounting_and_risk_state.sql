-- APEX-TRADER: align live Supabase schema with confirmed-fill accounting.
-- Additive and idempotent; does not modify or delete existing trading rows.

ALTER TABLE public.trades
  ADD COLUMN IF NOT EXISTS source varchar(20) DEFAULT 'engine',
  ADD COLUMN IF NOT EXISTS margin_usd numeric(18,4),
  ADD COLUMN IF NOT EXISTS notional_usd numeric(18,4),
  ADD COLUMN IF NOT EXISTS entry_quantity numeric(18,8),
  ADD COLUMN IF NOT EXISTS remaining_quantity numeric(18,8),
  ADD COLUMN IF NOT EXISTS take_profit_1_algo_id text,
  ADD COLUMN IF NOT EXISTS take_profit_2_algo_id text;

ALTER TABLE public.bot_state
  ADD COLUMN IF NOT EXISTS risk_day date;

COMMENT ON COLUMN public.trades.margin_usd IS 'Account margin allocated to the position';
COMMENT ON COLUMN public.trades.notional_usd IS 'Leveraged exchange notional at confirmed entry';
COMMENT ON COLUMN public.trades.entry_quantity IS 'Confirmed exchange-filled entry quantity';
COMMENT ON COLUMN public.trades.remaining_quantity IS 'Remaining exchange quantity after confirmed partial closes';
COMMENT ON COLUMN public.bot_state.risk_day IS 'UTC calendar day used for daily risk accounting';
