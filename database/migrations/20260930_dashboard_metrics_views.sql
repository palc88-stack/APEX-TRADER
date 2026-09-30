-- Refresh dashboard projections after execution metrics migration.

CREATE OR REPLACE VIEW public.dashboard_positions AS
SELECT
    t.id AS trade_id,
    t.symbol,
    t.direction,
    t.mode,
    t.strategy,
    t.strategy_subtype,
    t.exchange,
    t.status,
    t.entry_price,
    t.stop_loss,
    t.take_profit_1,
    t.take_profit_2,
    t.size_usd,
    t.notional_usd,
    t.leverage,
    t.entry_quantity,
    t.remaining_quantity,
    t.entry_fee,
    t.exit_fee,
    t.pnl,
    t.pnl_pct,
    t.pnl_account_pct,
    t.entry_slippage_bps,
    t.exit_slippage_bps,
    t.pnl_source,
    t.reconciliation_note,
    t.opened_at,
    t.closed_at,
    ps.slot_no,
    ps.status AS slot_status,
    ps.updated_at AS slot_updated_at
FROM public.trades t
LEFT JOIN public.position_slots ps ON ps.symbol = t.symbol
WHERE t.status IN ('OPEN', 'NEEDS_RECONCILIATION');

CREATE OR REPLACE VIEW public.dashboard_trade_summary AS
SELECT
    COUNT(*)::INTEGER AS total_trades,
    COUNT(*) FILTER (WHERE status = 'OPEN')::INTEGER AS open_trades,
    COUNT(*) FILTER (WHERE status = 'NEEDS_RECONCILIATION')::INTEGER AS unresolved_trades,
    COUNT(*) FILTER (WHERE status = 'CLOSED')::INTEGER AS closed_trades,
    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0)::INTEGER AS winning_trades,
    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl < 0)::INTEGER AS losing_trades,
    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl_source <> 'unconfirmed'), 0)::NUMERIC AS confirmed_realized_pnl,
    COALESCE(SUM(entry_fee + exit_fee) FILTER (WHERE status = 'CLOSED' AND pnl_source <> 'unconfirmed'), 0)::NUMERIC AS confirmed_fees,
    COALESCE(SUM(pnl_account_pct) FILTER (WHERE status = 'CLOSED' AND pnl_source <> 'unconfirmed'), 0)::NUMERIC AS confirmed_account_pnl_pct,
    MAX(opened_at) AS last_trade_at
FROM public.trades;
