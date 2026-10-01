-- A flat exchange position proves no remaining exposure, not an exit fill.
-- Keep this distinct from CLOSED so PnL cannot be fabricated.
ALTER TABLE public.trades
    ADD COLUMN IF NOT EXISTS exit_quantity NUMERIC(30, 12);

ALTER TABLE public.trades DROP CONSTRAINT IF EXISTS trades_status_check;
ALTER TABLE public.trades
    ADD CONSTRAINT trades_status_check
    CHECK (status IN ('OPEN', 'CLOSED', 'NEEDS_RECONCILIATION', 'RECONCILED_FLAT'));

ALTER TABLE public.trades DROP CONSTRAINT IF EXISTS trades_pnl_check;
ALTER TABLE public.trades
    ADD CONSTRAINT trades_pnl_check
    CHECK (status IN ('OPEN', 'NEEDS_RECONCILIATION', 'RECONCILED_FLAT') OR pnl IS NOT NULL) NOT VALID;

COMMENT ON COLUMN public.trades.exit_quantity IS
    'Exchange-confirmed exit quantity; NULL when reconciliation only proves zero exposure.';
