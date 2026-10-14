-- Track every daily reconciliation attempt, including skipped and failed runs.
-- Existing rows remain valid and are treated as completed historical runs.
ALTER TABLE public.reconciliation_runs
    ADD COLUMN IF NOT EXISTS run_status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS lease_name TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'reconciliation_runs_run_status_check'
          AND conrelid = 'public.reconciliation_runs'::regclass
    ) THEN
        ALTER TABLE public.reconciliation_runs
            ADD CONSTRAINT reconciliation_runs_run_status_check
            CHECK (run_status IN ('running', 'completed', 'failed', 'skipped'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_status_checked_at
    ON public.reconciliation_runs (run_status, checked_at DESC);

-- The Cloudflare Worker uses the service role to create and finalize run records.
GRANT INSERT, UPDATE ON TABLE public.reconciliation_runs TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.reconciliation_runs_id_seq TO service_role;
