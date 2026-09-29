-- APEX-TRADER realtime dashboard feeds.
-- Only state/event tables are published; no order-execution RPC is exposed.

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'bot_state',
        'trades',
        'position_slots',
        'universe_symbols',
        'reconciliation_runs',
        'trading_events'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_publication_tables
            WHERE pubname = 'supabase_realtime'
              AND schemaname = 'public'
              AND tablename = table_name
        ) THEN
            EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE public.%I', table_name);
        END IF;
    END LOOP;
END
$$;
