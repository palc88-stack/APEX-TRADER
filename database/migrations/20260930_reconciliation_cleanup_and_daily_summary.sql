-- Close stale zero-position reconciliation rows without inventing an exchange fill or PnL.
-- The unconfirmed rows remain excluded from realized-PnL totals.

ALTER TABLE public.trades DROP CONSTRAINT IF EXISTS trades_pnl_check;
ALTER TABLE public.trades
    ADD CONSTRAINT trades_pnl_check
    CHECK (
        status IN ('OPEN', 'NEEDS_RECONCILIATION')
        OR pnl IS NOT NULL
        OR (status = 'CLOSED' AND pnl_source = 'unconfirmed')
    );

CREATE OR REPLACE VIEW public.dashboard_daily_summary AS
SELECT
    date_trunc('day', NOW())::date AS risk_day,
    COUNT(*) FILTER (
        WHERE status = 'CLOSED'
          AND pnl_source <> 'unconfirmed'
          AND closed_at >= date_trunc('day', NOW())
    )::INTEGER AS confirmed_closed_trades,
    COALESCE(SUM(pnl) FILTER (
        WHERE status = 'CLOSED'
          AND pnl_source <> 'unconfirmed'
          AND closed_at >= date_trunc('day', NOW())
    ), 0)::NUMERIC AS confirmed_realized_pnl,
    COALESCE(SUM(GREATEST(-pnl, 0)) FILTER (
        WHERE status = 'CLOSED'
          AND pnl_source <> 'unconfirmed'
          AND closed_at >= date_trunc('day', NOW())
    ), 0)::NUMERIC AS confirmed_loss_used_usd,
    COALESCE(SUM(entry_fee + exit_fee) FILTER (
        WHERE status = 'CLOSED'
          AND pnl_source <> 'unconfirmed'
          AND closed_at >= date_trunc('day', NOW())
    ), 0)::NUMERIC AS confirmed_fees
FROM public.trades;

GRANT SELECT ON public.dashboard_daily_summary TO authenticated;
