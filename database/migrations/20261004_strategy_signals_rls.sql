-- Restrict strategy signal attribution records to authenticated dashboard readers
-- and the service role used by the bot.
ALTER TABLE public.strategy_signals ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.strategy_signals FROM anon;
REVOKE ALL ON TABLE public.strategy_signals FROM authenticated;

GRANT SELECT ON TABLE public.strategy_signals TO authenticated;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'strategy_signals'
      AND policyname = 'strategy_signals_authenticated_read'
  ) THEN
    CREATE POLICY strategy_signals_authenticated_read
      ON public.strategy_signals
      FOR SELECT
      TO authenticated
      USING (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'strategy_signals'
      AND policyname = 'strategy_signals_service_role_all'
  ) THEN
    CREATE POLICY strategy_signals_service_role_all
      ON public.strategy_signals
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true);
  END IF;
END
$$;
