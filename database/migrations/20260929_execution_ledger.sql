-- APEX-TRADER execution ledger
-- Phase 1: provenance, auditability, and idempotent execution records.
-- Additive only: does not alter order placement or existing trade rows.

CREATE TABLE IF NOT EXISTS public.trade_orders (
    id BIGSERIAL PRIMARY KEY,
    trade_id TEXT REFERENCES public.trades(id) ON DELETE SET NULL,
    exchange TEXT NOT NULL DEFAULT 'binance',
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted',
    exchange_order_id TEXT,
    client_order_id TEXT,
    requested_quantity NUMERIC(30, 12),
    requested_price NUMERIC(30, 12),
    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT trade_orders_side_check CHECK (LOWER(side) IN ('buy', 'sell')),
    CONSTRAINT trade_orders_status_check CHECK (
        status IN ('submitted', 'partially_filled', 'filled', 'canceled', 'rejected', 'unknown', 'needs_reconciliation')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_orders_exchange_order_id
    ON public.trade_orders (exchange, exchange_order_id)
    WHERE exchange_order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_orders_client_order_id
    ON public.trade_orders (exchange, client_order_id)
    WHERE client_order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trade_orders_trade_id
    ON public.trade_orders (trade_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_orders_symbol_status
    ON public.trade_orders (symbol, status, submitted_at DESC);

CREATE TABLE IF NOT EXISTS public.trade_fills (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT REFERENCES public.trade_orders(id) ON DELETE SET NULL,
    trade_id TEXT REFERENCES public.trades(id) ON DELETE SET NULL,
    exchange TEXT NOT NULL DEFAULT 'binance',
    symbol TEXT NOT NULL,
    exchange_order_id TEXT,
    exchange_fill_id TEXT,
    side TEXT NOT NULL,
    quantity NUMERIC(30, 12) NOT NULL,
    price NUMERIC(30, 12) NOT NULL,
    fee_amount NUMERIC(30, 12) NOT NULL DEFAULT 0,
    fee_currency TEXT,
    realized_pnl NUMERIC(30, 12),
    price_source TEXT NOT NULL DEFAULT 'exchange_fill',
    quantity_source TEXT NOT NULL DEFAULT 'exchange_fill',
    fee_source TEXT NOT NULL DEFAULT 'exchange_fill',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    filled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT trade_fills_side_check CHECK (LOWER(side) IN ('buy', 'sell')),
    CONSTRAINT trade_fills_quantity_check CHECK (quantity > 0),
    CONSTRAINT trade_fills_price_check CHECK (price > 0),
    CONSTRAINT trade_fills_fee_check CHECK (fee_amount >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_fills_exchange_fill_id
    ON public.trade_fills (exchange, exchange_fill_id)
    WHERE exchange_fill_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trade_fills_trade_id
    ON public.trade_fills (trade_id, filled_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_fills_order_id
    ON public.trade_fills (order_id, filled_at DESC);

CREATE TABLE IF NOT EXISTS public.trading_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    exchange TEXT,
    trade_id TEXT REFERENCES public.trades(id) ON DELETE SET NULL,
    order_id BIGINT REFERENCES public.trade_orders(id) ON DELETE SET NULL,
    symbol TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trading_events_trade_created
    ON public.trading_events (trade_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_events_type_created
    ON public.trading_events (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_events_symbol_created
    ON public.trading_events (symbol, created_at DESC);

ALTER TABLE public.trade_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trade_fills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trading_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.trade_orders, public.trade_fills, public.trading_events FROM anon, authenticated;
GRANT SELECT ON TABLE public.trade_orders, public.trade_fills, public.trading_events TO authenticated;

DROP POLICY IF EXISTS authenticated_read_trade_orders ON public.trade_orders;
CREATE POLICY authenticated_read_trade_orders ON public.trade_orders
    FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS authenticated_read_trade_fills ON public.trade_fills;
CREATE POLICY authenticated_read_trade_fills ON public.trade_fills
    FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS authenticated_read_trading_events ON public.trading_events;
CREATE POLICY authenticated_read_trading_events ON public.trading_events
    FOR SELECT TO authenticated USING (true);

COMMENT ON TABLE public.trade_orders IS 'Exchange order provenance and idempotent order identity.';
COMMENT ON TABLE public.trade_fills IS 'Exchange-confirmed fills; never infer fills from market candles.';
COMMENT ON TABLE public.trading_events IS 'Append-only operational audit events with idempotency keys.';
