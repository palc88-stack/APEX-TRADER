-- APEX-TRADER: live subtype performance view.
-- Read-only projection of confirmed closed trades; reconciliation rows are excluded.
CREATE OR REPLACE VIEW public.dashboard_strategy_subtype_performance AS
WITH grouped AS (
  SELECT
    COALESCE(NULLIF(strategy_subtype, ''), 'unknown') AS strategy_subtype,
    COUNT(*)::INTEGER AS closed_trades,
    COUNT(*) FILTER (WHERE pnl > 0)::INTEGER AS winning_trades,
    COUNT(*) FILTER (WHERE pnl < 0)::INTEGER AS losing_trades,
    COALESCE(SUM(pnl), 0)::NUMERIC AS realized_pnl,
    COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0)::NUMERIC AS average_win,
    COALESCE(AVG(pnl) FILTER (WHERE pnl < 0), 0)::NUMERIC AS average_loss,
    COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0)::NUMERIC AS gross_profit,
    ABS(COALESCE(SUM(pnl) FILTER (WHERE pnl < 0), 0))::NUMERIC AS gross_loss,
    COALESCE(AVG(exit_slippage_bps), 0)::NUMERIC AS average_exit_slippage_bps,
    MAX(closed_at) AS last_closed_at
  FROM public.trades
  WHERE status = 'CLOSED'
    AND pnl_source = 'exchange_fill'
    AND pnl IS NOT NULL
  GROUP BY COALESCE(NULLIF(strategy_subtype, ''), 'unknown')
)
SELECT
  strategy_subtype,
  closed_trades,
  winning_trades,
  losing_trades,
  CASE WHEN closed_trades > 0 THEN winning_trades::NUMERIC / closed_trades ELSE 0 END AS win_rate,
  realized_pnl,
  average_win,
  average_loss,
  gross_profit,
  gross_loss,
  CASE WHEN gross_loss > 0 THEN gross_profit / gross_loss ELSE NULL END AS profit_factor,
  CASE WHEN closed_trades > 0 THEN realized_pnl / closed_trades ELSE 0 END AS expectancy,
  average_exit_slippage_bps,
  last_closed_at
FROM grouped;
