-- Harden internal operational tables and SECURITY DEFINER functions.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'execution_leases',
    'pending_signals',
    'position_slots',
    'reconciliation_runs',
    'system_logs'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name);
    EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_service_role_all', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
      table_name || '_service_role_all', table_name
    );
  END LOOP;
END
$$;

REVOKE EXECUTE ON FUNCTION public.acquire_execution_lease(text, text, integer, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.activate_universe_snapshot(text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bind_position_slot(text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.release_execution_lease(text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.release_position_slot(text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.renew_execution_lease(text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.reserve_position_slot(text, text, text, integer) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.acquire_execution_lease(text, text, integer, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.activate_universe_snapshot(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.bind_position_slot(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.release_execution_lease(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.release_position_slot(text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_execution_lease(text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.reserve_position_slot(text, text, text, integer) TO service_role;

ALTER FUNCTION public.update_updated_at() SET search_path = public, pg_catalog;
ALTER FUNCTION public.handle_new_user() SET search_path = public, pg_catalog;
