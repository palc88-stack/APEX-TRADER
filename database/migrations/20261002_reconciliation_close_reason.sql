-- Reconciliation close reasons can be longer than the original trade labels.
-- This is metadata only; it does not submit or modify exchange orders.
ALTER TABLE public.trades
    ALTER COLUMN close_reason TYPE VARCHAR(64);
