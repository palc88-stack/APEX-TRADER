-- APEX-TRADER: dynamic universe and atomic global position slots.
-- Additive migration. No orders are sent and no existing trade rows are deleted.

CREATE TABLE IF NOT EXISTS universe_snapshots (
    id TEXT PRIMARY KEY,
    source VARCHAR(40) NOT NULL DEFAULT 'binance_usdm',
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS universe_symbols (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES universe_snapshots(id) ON DELETE CASCADE,
    symbol VARCHAR(30) NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    quote_volume_24h NUMERIC(30, 8) NOT NULL DEFAULT 0,
    spread_bps NUMERIC(12, 4) NOT NULL DEFAULT 0,
    liquidity_score NUMERIC(30, 8) NOT NULL DEFAULT 0,
    source VARCHAR(40) NOT NULL DEFAULT 'binance_usdm',
    selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (snapshot_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_universe_symbols_active_rank
    ON universe_symbols (is_active, rank);
CREATE INDEX IF NOT EXISTS idx_universe_symbols_expiry
    ON universe_symbols (expires_at);

ALTER TABLE universe_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE universe_symbols ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS authenticated_read_universe_snapshots ON universe_snapshots;
CREATE POLICY authenticated_read_universe_snapshots ON universe_snapshots
    FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS authenticated_read_universe_symbols ON universe_symbols;
CREATE POLICY authenticated_read_universe_symbols ON universe_symbols
    FOR SELECT TO authenticated USING (is_active = true);
REVOKE INSERT, UPDATE, DELETE ON TABLE universe_snapshots, universe_symbols FROM anon, authenticated;
GRANT SELECT ON TABLE universe_snapshots, universe_symbols TO authenticated;

CREATE OR REPLACE FUNCTION public.activate_universe_snapshot(p_snapshot_id TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    activated_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('apex-universe-activation'));
    UPDATE public.universe_symbols SET is_active = FALSE WHERE is_active = TRUE;
    UPDATE public.universe_snapshots SET is_active = FALSE WHERE is_active = TRUE;
    UPDATE public.universe_symbols SET is_active = TRUE WHERE snapshot_id = p_snapshot_id;
    GET DIAGNOSTICS activated_count = ROW_COUNT;
    UPDATE public.universe_snapshots SET is_active = TRUE WHERE id = p_snapshot_id;
    RETURN activated_count > 0;
END;
$$;

CREATE TABLE IF NOT EXISTS position_slots (
    slot_no SMALLINT PRIMARY KEY CHECK (slot_no > 0),
    symbol VARCHAR(30),
    trade_id TEXT,
    reservation_id TEXT,
    reservation_owner TEXT,
    status VARCHAR(12) NOT NULL DEFAULT 'free',
    reserved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT position_slots_status_check CHECK (status IN ('free', 'reserved', 'occupied')),
    CONSTRAINT position_slots_symbol_unique UNIQUE (symbol)
);

INSERT INTO position_slots (slot_no) VALUES (1), (2), (3)
ON CONFLICT (slot_no) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_position_slots_status ON position_slots (status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_position_slots_trade_id
    ON position_slots (trade_id) WHERE trade_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_position_slots_reservation_id
    ON position_slots (reservation_id) WHERE reservation_id IS NOT NULL;

ALTER TABLE position_slots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE position_slots FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.reserve_position_slot(
    p_symbol TEXT,
    p_owner TEXT,
    p_reservation_id TEXT,
    p_max_slots INTEGER DEFAULT 3
)
RETURNS SETOF public.position_slots
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    existing_slot public.position_slots;
    free_slot SMALLINT;
    active_count INTEGER;
BEGIN
    IF p_symbol IS NULL OR length(trim(p_symbol)) = 0 THEN
        RETURN;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('apex-position-slots'));

    SELECT * INTO existing_slot
      FROM public.position_slots
     WHERE symbol = upper(trim(p_symbol))
       AND status IN ('reserved', 'occupied')
     LIMIT 1;
    IF FOUND THEN
        RETURN NEXT existing_slot;
        RETURN;
    END IF;

    SELECT count(*) INTO active_count
      FROM public.position_slots
     WHERE status IN ('reserved', 'occupied');
    IF active_count >= greatest(1, least(p_max_slots, 100)) THEN
        RETURN;
    END IF;

    SELECT slot_no INTO free_slot
      FROM public.position_slots
     WHERE status = 'free'
     ORDER BY slot_no
     LIMIT 1
     FOR UPDATE;
    IF free_slot IS NULL THEN
        RETURN;
    END IF;

    UPDATE public.position_slots
       SET symbol = upper(trim(p_symbol)),
           reservation_id = p_reservation_id,
           reservation_owner = p_owner,
           status = 'reserved',
           reserved_at = now(),
           updated_at = now()
     WHERE slot_no = free_slot;
    RETURN QUERY SELECT * FROM public.position_slots WHERE slot_no = free_slot;
END;
$$;

CREATE OR REPLACE FUNCTION public.bind_position_slot(p_reservation_id TEXT, p_trade_id TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    UPDATE public.position_slots
       SET trade_id = p_trade_id, status = 'occupied', updated_at = now()
     WHERE reservation_id = p_reservation_id AND status = 'reserved';
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.release_position_slot(
    p_symbol TEXT DEFAULT NULL,
    p_trade_id TEXT DEFAULT NULL,
    p_reservation_id TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('apex-position-slots'));
    UPDATE public.position_slots
       SET symbol = NULL,
           trade_id = NULL,
           reservation_id = NULL,
           reservation_owner = NULL,
           status = 'free',
           reserved_at = NULL,
           updated_at = now()
     WHERE (p_symbol IS NOT NULL AND symbol = upper(trim(p_symbol)))
        OR (p_trade_id IS NOT NULL AND trade_id = p_trade_id)
        OR (p_reservation_id IS NOT NULL AND reservation_id = p_reservation_id);
    RETURN FOUND;
END;
$$;
