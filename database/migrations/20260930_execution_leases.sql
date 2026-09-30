-- Distributed execution lease for GitHub Actions, Cloudflare, and future Render workers.
-- The service-role key is required to call these SECURITY DEFINER RPCs.

CREATE TABLE IF NOT EXISTS public.execution_leases (
    lease_name TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    renewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_execution_leases_expires_at
    ON public.execution_leases (expires_at);

ALTER TABLE public.execution_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.execution_leases FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.acquire_execution_lease(
    p_lease_name TEXT,
    p_owner_id TEXT,
    p_ttl_seconds INTEGER DEFAULT 300,
    p_metadata JSONB DEFAULT '{}'::jsonb
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    IF COALESCE(length(trim(p_lease_name)), 0) = 0
       OR COALESCE(length(trim(p_owner_id)), 0) = 0 THEN
        RAISE EXCEPTION 'lease name and owner are required';
    END IF;
    IF p_ttl_seconds < 30 OR p_ttl_seconds > 900 THEN
        RAISE EXCEPTION 'invalid lease TTL';
    END IF;

    INSERT INTO public.execution_leases (
        lease_name, owner_id, acquired_at, renewed_at, expires_at, metadata
    )
    VALUES (
        p_lease_name,
        p_owner_id,
        NOW(),
        NOW(),
        NOW() + make_interval(secs => p_ttl_seconds),
        COALESCE(p_metadata, '{}'::jsonb)
    )
    ON CONFLICT (lease_name) DO UPDATE
    SET owner_id = EXCLUDED.owner_id,
        acquired_at = CASE
            WHEN execution_leases.owner_id = EXCLUDED.owner_id
              OR execution_leases.expires_at <= NOW()
            THEN NOW() ELSE execution_leases.acquired_at END,
        renewed_at = CASE
            WHEN execution_leases.owner_id = EXCLUDED.owner_id
              OR execution_leases.expires_at <= NOW()
            THEN NOW() ELSE execution_leases.renewed_at END,
        expires_at = CASE
            WHEN execution_leases.owner_id = EXCLUDED.owner_id
              OR execution_leases.expires_at <= NOW()
            THEN EXCLUDED.expires_at ELSE execution_leases.expires_at END,
        metadata = CASE
            WHEN execution_leases.owner_id = EXCLUDED.owner_id
              OR execution_leases.expires_at <= NOW()
            THEN EXCLUDED.metadata ELSE execution_leases.metadata END
    WHERE execution_leases.owner_id = EXCLUDED.owner_id
       OR execution_leases.expires_at <= NOW();

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.renew_execution_lease(
    p_lease_name TEXT,
    p_owner_id TEXT,
    p_ttl_seconds INTEGER DEFAULT 300
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    IF p_ttl_seconds < 30 OR p_ttl_seconds > 900 THEN
        RAISE EXCEPTION 'invalid lease TTL';
    END IF;

    UPDATE public.execution_leases
    SET renewed_at = NOW(),
        expires_at = NOW() + make_interval(secs => p_ttl_seconds)
    WHERE lease_name = p_lease_name
      AND owner_id = p_owner_id
      AND expires_at > NOW();

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.release_execution_lease(
    p_lease_name TEXT,
    p_owner_id TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    DELETE FROM public.execution_leases
    WHERE lease_name = p_lease_name
      AND owner_id = p_owner_id;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows = 1;
END;
$$;

GRANT EXECUTE ON FUNCTION public.acquire_execution_lease(TEXT, TEXT, INTEGER, JSONB)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_execution_lease(TEXT, TEXT, INTEGER)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.release_execution_lease(TEXT, TEXT)
    TO service_role;
