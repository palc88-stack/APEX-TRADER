-- Unconfirmed positions must not be forced to invent realized PnL.
ALTER TABLE public.trades DROP CONSTRAINT IF EXISTS trades_pnl_check;
ALTER TABLE public.trades
    ADD CONSTRAINT trades_pnl_check
    CHECK (((status)::text IN ('OPEN', 'NEEDS_RECONCILIATION')) OR pnl IS NOT NULL);
