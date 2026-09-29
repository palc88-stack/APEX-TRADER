-- APEX-TRADER dashboard read models
-- Phase 2: stable, read-only projections for the authenticated dashboard.

CREATE OR REPLACE VIEW public.dashboard_positions AS
SELECT
    t.id AS trade_id,
    t.symbol,
    t.direction,
    t.mode,
    t.strategy,
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
    t.pnl_source,
    t.reconciliation_note,
    t.opened_at,
    t.closed_at,
    ps.slot_no,
    ps.status AS slot_status,
    ps.updated_at AS slot_updated_at
FROM public.trades t
LEFT JOIN public.position_slots ps
  ON ps.symbol = t.symbol
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
    MAX(opened_at) AS last_trade_at
FROM public.trades;

CREATE OR REPLACE VIEW public.dashboard_risk_state AS
SELECT
    b.id,
    b.bot_status,
    b.environment,
    b.is_running,
    b.is_paused,
    b.heartbeat_at,
    b.cycle_completed_at,
    b.current_balance,
    b.available_balance,
    b.daily_loss_used_usd,
    b.daily_loss_limit_usd,
    b.daily_realized_pnl,
    b.active_mode,
    b.error_count,
    b.last_error,
    COALESCE(s.active_slots, 0)::INTEGER AS active_slots,
    3::INTEGER AS max_slots,
    COALESCE(u.unresolved_trades, 0)::INTEGER AS unresolved_trades,
    CASE
      WHEN COALESCE(u.unresolved_trades, 0) > 0 THEN 'blocked_reconciliation'
      WHEN COALESCE(s.active_slots, 0) >= 3 THEN 'at_slot_limit'
      ELSE 'ready_for_testnet'
    END AS entry_gate
FROM public.bot_state b
LEFT JOIN (
    SELECT COUNT(*)::INTEGER AS active_slots
    FROM public.position_slots
    WHERE status IN ('reserved', 'occupied')
) s ON TRUE
LEFT JOIN (
    SELECT COUNT(*)::INTEGER AS unresolved_trades
    FROM public.trades
    WHERE status = 'NEEDS_RECONCILIATION'
) u ON TRUE
WHERE b.id = 1;

CREATE OR REPLACE VIEW public.dashboard_universe AS
SELECT
    symbol,
    rank,
    quote_volume_24h,
    spread_bps,
    liquidity_score,
    source,
    selected_at,
    expires_at,
    snapshot_id
FROM public.universe_symbols
WHERE is_active = TRUE
  AND expires_at > NOW()
ORDER BY rank;

CREATE OR REPLACE VIEW public.dashboard_reconciliation_status AS
SELECT
    r.id AS run_id,
    r.checked_at,
    r.source,
    r.db_open_count,
    r.exchange_open_count,
    r.occupied_slot_count,
    r.finding_count,
    r.findings,
    COALESCE(u.unresolved_trades, 0)::INTEGER AS unresolved_trades,
    CASE
      WHEN COALESCE(r.finding_count, 0) > 0 OR COALESCE(u.unresolved_trades, 0) > 0 THEN 'attention_required'
      ELSE 'clear'
    END AS status
FROM public.reconciliation_runs r
LEFT JOIN (
    SELECT COUNT(*)::INTEGER AS unresolved_trades
    FROM public.trades
    WHERE status = 'NEEDS_RECONCILIATION'
) u ON TRUE
ORDER BY r.checked_at DESC
LIMIT 1;

REVOKE ALL ON public.dashboard_positions,
    public.dashboard_trade_summary,
    public.dashboard_risk_state,
    public.dashboard_universe,
    public.dashboard_reconciliation_status
FROM anon;
GRANT SELECT ON public.dashboard_positions,
    public.dashboard_trade_summary,
    public.dashboard_risk_state,
    public.dashboard_universe,
    public.dashboard_reconciliation_status
TO authenticated;
